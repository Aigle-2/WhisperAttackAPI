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
                        // These VoiceAttack command names match the bundled profile
                        // ("VAIVOX - VA Profile.vap"); bind your PTT buttons to them.
                        case "Start Whisper Recording":
                            {
                                byte[] data = Encoding.ASCII.GetBytes("start");
                                stream.Write(data, 0, data.Length);
                                vaProxy.WriteToLog("Start VAIVOX recording", "grey");
                                break;
                            }

                        case "Stop Whisper Recording":
                            {
                                byte[] data = Encoding.ASCII.GetBytes("stop");
                                stream.Write(data, 0, data.Length);
                                vaProxy.WriteToLog("Stop VAIVOX recording", "grey");
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
            _listener.Stop();

            using (TcpClient client = new TcpClient(Server, ControlPort))
            using (NetworkStream stream = client.GetStream())
            {
                byte[] data = Encoding.ASCII.GetBytes("shutdown");
                stream.Write(data, 0, data.Length);
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
                    await HandleVaivoxCommand(vaProxy, await _listener.AcceptTcpClientAsync());
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

                    if (vaProxy.Command.Exists(receivedMessage))
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
    }
}
