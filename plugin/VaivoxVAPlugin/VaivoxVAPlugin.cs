using System;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;

namespace VaivoxServerCommand
{
    /// <summary>
    /// Result of deciding whether VoiceAttack has (and dispatched) a command for a
    /// piece of text. Pure data — no VoiceAttack dependency — so it is unit-testable.
    /// </summary>
    public struct MatchResult
    {
        public bool Matched;
        public string ResolvedCommand;

        public MatchResult(bool matched, string resolvedCommand)
        {
            Matched = matched;
            ResolvedCommand = resolvedCommand;
        }
    }

    /// <summary>
    /// Seam over VoiceAttack's command surface (<c>vaProxy.Command.Exists/Execute</c>).
    /// Lets <see cref="VA_Plugin.Decide"/> be tested with an in-memory fake — no
    /// <c>vaProxy</c>, no VoiceAttack install.
    /// </summary>
    public interface ICommandProbe
    {
        bool Exists(string text);
        void Execute(string text);
    }

    public class VA_Plugin
    {
        // Ports mirror VAIVOX's ProductIdentity (ADR-0002): the app's inbound control
        // socket is 65432; this plugin's listener (for results) is 65433.
        private const string Server = "127.0.0.1";
        private const int ControlPort = 65432;
        private const int ListenerPort = 65433;
        private const string StartVaivoxRecordingContext = "Start VAIVOX Recording";
        private const string StopVaivoxRecordingContext = "Stop VAIVOX Recording";

        private static bool _isRunning = true;
        private static TcpListener _listener = null;

        public static string VA_DisplayName()
        {
            return "VAIVOX";
        }

        public static string VA_DisplayInfo()
        {
            return "VAIVOX Server Command plugin";
        }

        public static Guid VA_Id()
        {
            // Fresh GUID for VAIVOX — distinct from the upstream WhisperAttack plugin
            // so VoiceAttack treats it as a separate plugin (ADR-0002). The bundled
            // "VAIVOX - VA Profile.vap" binds the plugin by THIS GUID; do not change it.
            return new Guid("{ED0BA443-726F-4A9F-AF05-DB400F39A501}");
        }

        public static void VA_StopCommand()
        {
        }

        /// <summary>
        /// The plugin assembly version (from <c>VaivoxVAPlugin.csproj</c>'s
        /// <c>AssemblyVersion</c>), e.g. <c>"1.0.0.0"</c>. Logged at the
        /// <see cref="VA_Init1"/> handshake next to <see cref="MatchProtocolVersion"/> so a
        /// plugin/app version mismatch is visible in the VoiceAttack log (M6 version stamp).
        /// </summary>
        public static string AssemblyVersion()
        {
            Version version = Assembly.GetExecutingAssembly().GetName().Version;
            return version != null ? version.ToString() : "unknown";
        }

        public static void VA_Init1(dynamic vaProxy)
        {
            // Version stamp (M6): log the plugin assembly + return-channel protocol version
            // at startup so a plugin/app mismatch is visible. The protocol version mirrors
            // Python's MATCH_PROTOCOL_VERSION (protocol.py) — the two are independently
            // pinned and asserted equal by the shared golden vectors.
            vaProxy.WriteToLog(
                string.Format(
                    CultureInfo.InvariantCulture,
                    "VAIVOX plugin {0}, match protocol v{1}",
                    AssemblyVersion(),
                    MatchProtocolVersion),
                "blue");

            try
            {
                using (TcpClient client = new TcpClient(Server, ControlPort))
                using (NetworkStream stream = client.GetStream())
                {
                    vaProxy.WriteToLog("Connected to VAIVOX server", "blue");
                }
            }
            catch (Exception ex)
            {
                vaProxy.WriteToLog($"Failed to connect to VAIVOX server: {ex.Message}", "red");
            }

            StartCommandListener(vaProxy);
        }

        public static void VA_Invoke1(dynamic vaProxy)
        {
            string contextinput = vaProxy.Context;

            try
            {
                using (TcpClient client = new TcpClient(Server, ControlPort))
                using (NetworkStream stream = client.GetStream())
                {
                    switch (contextinput)
                    {
                        case StartVaivoxRecordingContext:
                            {
                                SendControlCommand(stream, "start");
                                vaProxy.WriteToLog("Start VAIVOX recording", "grey");
                                break;
                            }

                        case StopVaivoxRecordingContext:
                            {
                                SendControlCommand(stream, "stop");
                                vaProxy.WriteToLog("Stop VAIVOX recording", "grey");
                                break;
                            }

                        default:
                            {
                                vaProxy.WriteToLog($"Unknown VAIVOX plugin context: {contextinput}", "orange");
                                break;
                            }
                    }
                }
            }
            catch (Exception ex)
            {
                vaProxy.WriteToLog($"VAIVOX server command error: {ex.Message}", "red");
            }
        }

        public static void VA_Exit1(dynamic vaProxy)
        {
            _isRunning = false;
            try
            {
                if (_listener != null)
                {
                    _listener.Stop();
                    _listener = null;
                }
            }
            catch (ObjectDisposedException)
            {
                // Listener is already closed; VoiceAttack exit should not tear down VAIVOX.
            }
        }

        private static void SendControlCommand(NetworkStream stream, string command)
        {
            byte[] data = Encoding.ASCII.GetBytes(command);
            stream.Write(data, 0, data.Length);
        }

        // ---------------------------------------------------------------------
        // Return channel (ADR-0006). Pure, vaProxy-free logic — unit-tested in
        // plugin/VaivoxVAPlugin.Tests against the shared golden vectors
        // (tests/contract/match_protocol_vectors.json), so the C# reply is
        // guaranteed byte-identical to the Python build_reply (protocol.py).
        // ---------------------------------------------------------------------

        /// <summary>
        /// The wire-protocol version emitted in the <c>"v"</c> field of every reply
        /// (matches <c>MATCH_PROTOCOL_VERSION</c> in protocol.py).
        /// </summary>
        public const int MatchProtocolVersion = 1;

        /// <summary>
        /// Serialize a match outcome to the reference reply bytes.
        ///
        /// Reproduces, byte-for-byte, the Python reference serialization in
        /// <c>protocol.py::build_reply</c>: a compact (no inter-token whitespace),
        /// single-line UTF-8 JSON object with the stable key order
        /// <c>v</c>, <c>matched</c>, <c>resolved_command</c>, terminated by a single
        /// <c>\n</c> (LF). <c>resolved_command</c> is the literal <c>null</c> when it
        /// is null. Strings are emitted with <c>ensure_ascii=False</c> semantics
        /// (raw UTF-8, no <c>\uXXXX</c> escaping of non-ASCII) and minimal JSON
        /// escaping of <c>"</c>, <c>\</c>, and the C0 control characters.
        ///
        /// The string is built by hand on purpose: a general-purpose JSON serializer
        /// might reorder keys, insert spaces, or escape differently, which would
        /// break the byte-identical contract.
        /// </summary>
        public static string BuildReply(bool matched, string resolvedCommand)
        {
            var sb = new StringBuilder();
            sb.Append("{\"v\":");
            sb.Append(MatchProtocolVersion.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"matched\":");
            sb.Append(matched ? "true" : "false");
            sb.Append(",\"resolved_command\":");
            if (resolvedCommand == null)
            {
                sb.Append("null");
            }
            else
            {
                AppendJsonString(sb, resolvedCommand);
            }
            sb.Append("}\n");
            return sb.ToString();
        }

        /// <summary>
        /// Append <paramref name="value"/> as a JSON string literal, matching
        /// Python's <c>json.dumps(..., ensure_ascii=False)</c>: wrap in double
        /// quotes, escape <c>"</c> and <c>\</c>, use the short escapes for the
        /// control characters that have them (<c>\b \t \n \f \r</c>), emit the
        /// remaining C0 controls (U+0000–U+001F) as <c>\u00XX</c>, and pass every
        /// other character (including all non-ASCII) through untouched as raw UTF-8.
        /// </summary>
        private static void AppendJsonString(StringBuilder sb, string value)
        {
            sb.Append('"');
            foreach (char c in value)
            {
                switch (c)
                {
                    case '"':
                        sb.Append("\\\"");
                        break;
                    case '\\':
                        sb.Append("\\\\");
                        break;
                    case '\b':
                        sb.Append("\\b");
                        break;
                    case '\t':
                        sb.Append("\\t");
                        break;
                    case '\n':
                        sb.Append("\\n");
                        break;
                    case '\f':
                        sb.Append("\\f");
                        break;
                    case '\r':
                        sb.Append("\\r");
                        break;
                    default:
                        if (c < 0x20)
                        {
                            sb.Append("\\u");
                            sb.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            sb.Append(c);
                        }
                        break;
                }
            }
            sb.Append('"');
        }

        /// <summary>
        /// Decide the match outcome for <paramref name="text"/>: if the probe reports
        /// the command exists, execute it and return matched=true with the text as the
        /// resolved command; otherwise return matched=false with a null resolved
        /// command. <c>Execute</c> is called only when <c>Exists</c> is true.
        /// </summary>
        public static MatchResult Decide(ICommandProbe probe, string text)
        {
            if (probe.Exists(text))
            {
                probe.Execute(text);
                return new MatchResult(true, text);
            }

            return new MatchResult(false, null);
        }

        /// <summary>
        /// Real <see cref="ICommandProbe"/> backed by VoiceAttack's
        /// <c>vaProxy.Command</c> surface. <c>Execute</c> is <b>deferred</b>: it records
        /// that the command should run but does not call into VoiceAttack yet, so the
        /// handler can send the match reply on the socket <i>before</i> the (potentially
        /// slow) in-game radio call runs (v1's low-latency return-channel ordering,
        /// ADR-0006). The handler flushes the deferred execute via <see cref="RunDeferred"/>
        /// after the reply has been written. All decision logic stays in the testable
        /// <see cref="Decide"/>; only the side effect is deferred.
        /// </summary>
        private sealed class VaProxyCommandProbe : ICommandProbe
        {
            private readonly dynamic _vaProxy;
            private string _deferredExecute;

            public VaProxyCommandProbe(dynamic vaProxy)
            {
                _vaProxy = vaProxy;
            }

            public bool Exists(string text)
            {
                return _vaProxy.Command.Exists(text);
            }

            public void Execute(string text)
            {
                // Defer the real dispatch so the reply goes out first (see class docs).
                _deferredExecute = text;
            }

            /// <summary>
            /// Run the dispatch that <see cref="Execute"/> deferred, if any. Called by the
            /// handler after the match reply has been written to the socket.
            /// </summary>
            public void RunDeferred()
            {
                if (_deferredExecute != null)
                {
                    _vaProxy.Command.Execute(_deferredExecute, true, true);
                    _deferredExecute = null;
                }
            }
        }

        private static async Task StartCommandListener(dynamic vaProxy)
        {
            vaProxy.WriteToLog($"Starting VAIVOX listener on {ListenerPort}", "blue");

            try
            {
                _listener = new TcpListener(IPAddress.Loopback, ListenerPort);
                _listener.Start();

                vaProxy.WriteToLog("VAIVOX listener started", "blue");

                while (_isRunning)
                {
                    try
                    {
                        await HandleVaivoxCommand(vaProxy, await _listener.AcceptTcpClientAsync());
                    }
                    catch (ObjectDisposedException) when (!_isRunning)
                    {
                        break;
                    }
                    catch (SocketException) when (!_isRunning)
                    {
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                vaProxy.WriteToLog($"Error starting VAIVOX listener: {ex.Message}", "red");
            }
        }

        private static async Task HandleVaivoxCommand(dynamic vaProxy, TcpClient client)
        {
            await Task.Yield();

            using (NetworkStream stream = client.GetStream())
            {
                try
                {
                    byte[] buffer = new byte[1024];
                    int bytesRead = await stream.ReadAsync(buffer, 0, buffer.Length);
                    string receivedMessage = Encoding.UTF8.GetString(buffer, 0, bytesRead);

                    vaProxy.WriteToLog($"Received VAIVOX command: '{receivedMessage}'", "grey");

                    // ADR-0006 return channel: decide the match, reply on the SAME socket,
                    // THEN run the dispatch. Decide() drives the (testable) ICommandProbe;
                    // the real probe defers Command.Execute so the reply round-trip stays
                    // off the (potentially slow) in-game radio call and the server learns
                    // the outcome with negligible latency (v1 ordering preserved). The
                    // resolved value is the submitted profile phrase, including canonical
                    // VAICOM `Action ...` aliases.
                    VaProxyCommandProbe probe = new VaProxyCommandProbe(vaProxy);
                    MatchResult result = Decide(probe, receivedMessage);

                    // Return channel (ADR-0006): reply on the same connection with the
                    // match outcome BEFORE dispatching. Best-effort — an old app that does
                    // not read the reply makes this Write hit a broken pipe; tolerate it
                    // (compat matrix) so the plugin keeps working against any app version.
                    try
                    {
                        byte[] reply = Encoding.UTF8.GetBytes(
                            BuildReply(result.Matched, result.ResolvedCommand));
                        await stream.WriteAsync(reply, 0, reply.Length);
                        await stream.FlushAsync();
                    }
                    catch (Exception writeEx)
                    {
                        // Broken pipe / connection reset by an old (non-reading) app.
                        vaProxy.WriteToLog(
                            $"Match reply not delivered (old app?): {writeEx.Message}", "grey");
                    }

                    if (result.Matched)
                    {
                        probe.RunDeferred();
                        vaProxy.WriteToLog($"Executed command '{receivedMessage}'", "green");
                    }
                    else
                    {
                        vaProxy.WriteToLog($"Command '{receivedMessage}' not found", "orange");
                    }
                }
                catch (Exception ex)
                {
                    vaProxy.WriteToLog($"Error reading command: {ex.Message}", "red");
                }
            }
        }
    }
}
