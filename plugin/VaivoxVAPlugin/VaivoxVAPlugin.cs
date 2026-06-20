using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;

namespace VaivoxServerCommand
{
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
            // so VoiceAttack treats it as a separate plugin (ADR-0002).
            return new Guid("{ED0BA443-726F-4A9F-AF05-DB400F39A501}");
        }

        public static void VA_StopCommand()
        {
        }

        public static void VA_Init1(dynamic vaProxy)
        {
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
                // Listener is already closed; shutdown is intentionally best-effort.
            }

            try
            {
                using (TcpClient client = new TcpClient(Server, ControlPort))
                using (NetworkStream stream = client.GetStream())
                {
                    byte[] data = Encoding.ASCII.GetBytes("shutdown");
                    stream.Write(data, 0, data.Length);
                }
            }
            catch (Exception ex)
            {
                vaProxy.WriteToLog($"VAIVOX server was not available during shutdown: {ex.Message}", "grey");
            }
        }

        private static void SendControlCommand(NetworkStream stream, string command)
        {
            byte[] data = Encoding.ASCII.GetBytes(command);
            stream.Write(data, 0, data.Length);
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
                    // then dispatch. Replying before Command.Execute keeps the round-trip off
                    // the (potentially slow) in-game radio call, so the server learns the
                    // outcome with negligible latency. The resolved value is the submitted
                    // profile phrase, including canonical VAICOM `Action ...` aliases.
                    bool matched = vaProxy.Command.Exists(receivedMessage);
                    string resolvedCommand = matched ? receivedMessage : null;
                    await SendMatchOutcome(stream, receivedMessage, matched, resolvedCommand);

                    if (matched)
                    {
                        vaProxy.Command.Execute(receivedMessage, true, true);
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

        // The VAIVOX server reads one JSON line back on the command socket right after it
        // sends the command (ADR-0006). The reply is best-effort: a server running an older
        // build simply will not read it, and any failure here must never break dispatch.
        private static async Task SendMatchOutcome(
            NetworkStream stream, string text, bool matched, string resolvedCommand)
        {
            try
            {
                string payload = BuildOutcomeJson(text, matched, resolvedCommand) + "\n";
                byte[] data = Encoding.UTF8.GetBytes(payload);
                await stream.WriteAsync(data, 0, data.Length);
            }
            catch (Exception)
            {
                // A missing or short reply is treated as "unknown" by the server, which then
                // records the event without stamping usage and carries on — so swallow any
                // write/socket error rather than throwing across the plugin boundary.
            }
        }

        // Build the { text, matched, resolved_command } reply by hand so the plugin keeps
        // zero third-party dependencies (no JSON library); resolved_command is null when the
        // command did not match.
        private static string BuildOutcomeJson(string text, bool matched, string resolvedCommand)
        {
            string matchedLiteral = matched ? "true" : "false";
            return "{\"text\": " + JsonStringOrNull(text)
                + ", \"matched\": " + matchedLiteral
                + ", \"resolved_command\": " + JsonStringOrNull(resolvedCommand) + "}";
        }

        // Serialize a string as a JSON string literal with the required escaping, or the
        // literal `null` for a null value.
        private static string JsonStringOrNull(string value)
        {
            if (value == null)
            {
                return "null";
            }

            StringBuilder builder = new StringBuilder(value.Length + 2);
            builder.Append('"');
            foreach (char c in value)
            {
                switch (c)
                {
                    case '"': builder.Append("\\\""); break;
                    case '\\': builder.Append("\\\\"); break;
                    case '\b': builder.Append("\\b"); break;
                    case '\f': builder.Append("\\f"); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    default:
                        if (c < ' ')
                        {
                            builder.Append("\\u").Append(((int)c).ToString("x4"));
                        }
                        else
                        {
                            builder.Append(c);
                        }
                        break;
                }
            }
            builder.Append('"');
            return builder.ToString();
        }
    }
}
