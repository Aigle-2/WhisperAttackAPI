using System.Collections.Generic;
using VaivoxServerCommand;
using Xunit;

namespace VaivoxVAPlugin.Tests
{
    /// <summary>
    /// AC4: VA_Plugin.Decide drives an ICommandProbe correctly — matched when the
    /// command exists (and only then is Execute called), not-matched otherwise. Uses an
    /// in-memory fake probe, so no vaProxy and no VoiceAttack are involved.
    /// </summary>
    public class DecideTests
    {
        /// <summary>Records what was probed/executed so tests can assert on it.</summary>
        private sealed class FakeCommandProbe : ICommandProbe
        {
            private readonly HashSet<string> _known;

            public FakeCommandProbe(params string[] known)
            {
                _known = new HashSet<string>(known);
            }

            public List<string> ExistsCalls { get; } = new List<string>();
            public List<string> ExecuteCalls { get; } = new List<string>();

            public bool Exists(string text)
            {
                ExistsCalls.Add(text);
                return _known.Contains(text);
            }

            public void Execute(string text)
            {
                ExecuteCalls.Add(text);
            }
        }

        [Fact]
        public void Decide_returns_matched_and_executes_when_command_exists()
        {
            var probe = new FakeCommandProbe("Tower, request taxi");

            var result = VA_Plugin.Decide(probe, "Tower, request taxi");

            Assert.True(result.Matched);
            Assert.Equal("Tower, request taxi", result.ResolvedCommand);
            Assert.Equal(new[] { "Tower, request taxi" }, probe.ExecuteCalls.ToArray());
            Assert.Equal(new[] { "Tower, request taxi" }, probe.ExistsCalls.ToArray());
        }

        [Fact]
        public void Decide_returns_not_matched_and_does_not_execute_when_missing()
        {
            var probe = new FakeCommandProbe(); // nothing exists

            var result = VA_Plugin.Decide(probe, "unknown command");

            Assert.False(result.Matched);
            Assert.Null(result.ResolvedCommand);
            Assert.Empty(probe.ExecuteCalls); // Execute is NOT called on a miss.
            Assert.Equal(new[] { "unknown command" }, probe.ExistsCalls.ToArray());
        }

        [Fact]
        public void Decide_round_trips_into_a_golden_reply_when_matched()
        {
            var probe = new FakeCommandProbe("RTB");

            var result = VA_Plugin.Decide(probe, "RTB");
            var reply = VA_Plugin.BuildReply(result.Matched, result.ResolvedCommand);

            Assert.Equal("{\"v\":1,\"matched\":true,\"resolved_command\":\"RTB\"}\n", reply);
        }

        [Fact]
        public void Decide_round_trips_into_a_golden_reply_when_not_matched()
        {
            var probe = new FakeCommandProbe();

            var result = VA_Plugin.Decide(probe, "nope");
            var reply = VA_Plugin.BuildReply(result.Matched, result.ResolvedCommand);

            Assert.Equal("{\"v\":1,\"matched\":false,\"resolved_command\":null}\n", reply);
        }
    }
}
