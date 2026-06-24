using System.Collections.Generic;
using System.Linq;
using System.Text;
using VaivoxServerCommand;
using Xunit;

namespace VaivoxVAPlugin.Tests
{
    /// <summary>
    /// AC4: VA_Plugin.BuildReply must serialize byte-identically to the Python
    /// reference (protocol.py::build_reply), proven against the shared golden vectors
    /// (tests/contract/match_protocol_vectors.json). Only the <c>round_trip</c> vectors
    /// are exercised here — the <c>parse_only</c> vectors are the Python parser's job.
    /// </summary>
    public class BuildReplyTests
    {
        public static IEnumerable<object[]> RoundTripVectors()
        {
            foreach (var vector in GoldenVectors.RoundTrip())
            {
                yield return new object[] { vector };
            }
        }

        [Theory]
        [MemberData(nameof(RoundTripVectors))]
        public void BuildReply_matches_golden_string(RoundTripVector vector)
        {
            var actual = VA_Plugin.BuildReply(vector.Matched, vector.ResolvedCommand);
            Assert.Equal(vector.ReplyBytes, actual);
        }

        [Theory]
        [MemberData(nameof(RoundTripVectors))]
        public void BuildReply_matches_golden_utf8_bytes(RoundTripVector vector)
        {
            // The contract is about *bytes on the wire*. Compare the raw UTF-8 encoding,
            // so non-ASCII (e.g. "Décollage immédiat") is verified as raw UTF-8 with no
            // \uXXXX escaping, and the trailing LF is included.
            var expected = Encoding.UTF8.GetBytes(vector.ReplyBytes);
            var actual = Encoding.UTF8.GetBytes(
                VA_Plugin.BuildReply(vector.Matched, vector.ResolvedCommand));
            Assert.True(
                expected.SequenceEqual(actual),
                $"Bytes differ for vector '{vector.Name}'.\n" +
                $"expected: {ToHex(expected)}\n" +
                $"actual:   {ToHex(actual)}");
        }

        [Fact]
        public void BuildReply_ends_with_single_lf()
        {
            var reply = VA_Plugin.BuildReply(true, "RTB");
            Assert.EndsWith("}\n", reply);
            Assert.DoesNotContain("\r", reply); // LF only, never CRLF.
            Assert.Equal(1, reply.Count(ch => ch == '\n'));
        }

        [Fact]
        public void BuildReply_emits_null_for_missing_resolved_command()
        {
            Assert.Equal("{\"v\":1,\"matched\":false,\"resolved_command\":null}\n",
                VA_Plugin.BuildReply(false, null));
        }

        [Fact]
        public void BuildReply_is_compact_with_stable_key_order()
        {
            var reply = VA_Plugin.BuildReply(true, "x");
            // No inter-token whitespace; keys in v, matched, resolved_command order.
            Assert.Equal("{\"v\":1,\"matched\":true,\"resolved_command\":\"x\"}\n", reply);
        }

        [Theory]
        [InlineData("with \"quotes\"", "{\"v\":1,\"matched\":true,\"resolved_command\":\"with \\\"quotes\\\"\"}\n")]
        [InlineData("back\\slash", "{\"v\":1,\"matched\":true,\"resolved_command\":\"back\\\\slash\"}\n")]
        [InlineData("tab\there", "{\"v\":1,\"matched\":true,\"resolved_command\":\"tab\\there\"}\n")]
        [InlineData("new\nline", "{\"v\":1,\"matched\":true,\"resolved_command\":\"new\\nline\"}\n")]
        public void BuildReply_escapes_json_special_chars_like_python(string resolved, string expected)
        {
            Assert.Equal(expected, VA_Plugin.BuildReply(true, resolved));
        }

        [Fact]
        public void BuildReply_escapes_low_control_char_as_u_escape()
        {
            // U+0001 has no short escape -> lowercase \u00XX, matching json.dumps.
            var reply = VA_Plugin.BuildReply(true, "");
            Assert.Equal("{\"v\":1,\"matched\":true,\"resolved_command\":\"\\u0001\"}\n", reply);
        }

        [Fact]
        public void BuildReply_passes_non_ascii_through_raw()
        {
            // ensure_ascii=False semantics: non-ASCII stays raw, not \uXXXX.
            var reply = VA_Plugin.BuildReply(true, "Décollage immédiat");
            Assert.Contains("Décollage immédiat", reply);
            Assert.DoesNotContain("\\u", reply);
        }

        private static string ToHex(byte[] bytes)
        {
            var sb = new StringBuilder();
            foreach (var b in bytes)
            {
                sb.Append(b.ToString("x2"));
                sb.Append(' ');
            }

            return sb.ToString().TrimEnd();
        }
    }
}
