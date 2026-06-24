using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace VaivoxVAPlugin.Tests
{
    /// <summary>
    /// A single <c>round_trip</c> golden vector from
    /// <c>tests/contract/match_protocol_vectors.json</c> — the shared source of truth
    /// the Python serializer (protocol.py::build_reply) and this C# plugin
    /// (VA_Plugin.BuildReply) must both reproduce byte-for-byte (AC1/AC4).
    /// </summary>
    public sealed class RoundTripVector
    {
        public string Name { get; }
        public bool Matched { get; }

        // null when resolved_command is JSON null; otherwise the string value.
        public string ResolvedCommand { get; }

        // The expected reply line (with trailing "\n"), decoded from the JSON-escaped
        // "reply_bytes" string in the vectors file.
        public string ReplyBytes { get; }

        public RoundTripVector(string name, bool matched, string resolvedCommand, string replyBytes)
        {
            Name = name;
            Matched = matched;
            ResolvedCommand = resolvedCommand;
            ReplyBytes = replyBytes;
        }

        public override string ToString()
        {
            return Name;
        }
    }

    /// <summary>
    /// Loads the shared golden vectors, locating the repo root by walking up from the
    /// test assembly's base directory until it finds
    /// <c>tests/contract/match_protocol_vectors.json</c>. Robust to the build output
    /// depth (bin/Debug/net8.0/...) and to the CI working directory.
    /// </summary>
    public static class GoldenVectors
    {
        private const string RelativeVectorsPath =
            "tests/contract/match_protocol_vectors.json";

        public static string VectorsFilePath()
        {
            // Start from the test DLL location and climb to the repo root.
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null)
            {
                var candidate = Path.Combine(
                    dir.FullName,
                    "tests",
                    "contract",
                    "match_protocol_vectors.json");
                if (File.Exists(candidate))
                {
                    return candidate;
                }

                dir = dir.Parent;
            }

            throw new FileNotFoundException(
                $"Could not locate '{RelativeVectorsPath}' walking up from " +
                $"'{AppContext.BaseDirectory}'. Run the tests from inside the repo.");
        }

        public static List<RoundTripVector> RoundTrip()
        {
            var json = File.ReadAllText(VectorsFilePath());
            using var doc = JsonDocument.Parse(json);

            var vectors = new List<RoundTripVector>();
            foreach (var element in doc.RootElement.GetProperty("round_trip").EnumerateArray())
            {
                var name = element.GetProperty("name").GetString();
                var matched = element.GetProperty("matched").GetBoolean();

                var resolvedProp = element.GetProperty("resolved_command");
                string resolved =
                    resolvedProp.ValueKind == JsonValueKind.Null
                        ? null
                        : resolvedProp.GetString();

                // GetString() returns the *decoded* string; one JSON "\n" escape
                // becomes a single LF, so this is the exact byte content expected.
                var replyBytes = element.GetProperty("reply_bytes").GetString();

                vectors.Add(new RoundTripVector(name, matched, resolved, replyBytes));
            }

            return vectors;
        }
    }
}
