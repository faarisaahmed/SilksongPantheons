using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Notices a boss that has left the arena, says exactly how, and brings it back.
    ///
    /// This is a net, not a fix. Oro was reported as jumping too far up and
    /// disappearing, and his graph explains why it is possible but not why it happens:
    /// his Jump state sets a vertical velocity of 60 and relies on either gravity or a
    /// floor collision to end the arc, and the state that restores his gravity scale
    /// (Activate) is reached through an arena entry sequence that a spawned boss never
    /// runs. Which of those is failing is not decidable from the baked data - it needs
    /// the runtime.
    ///
    /// So this logs the boss's FSM states, position and rigidbody the moment it leaves
    /// the room, which names the cause on the next report, and then returns it rather
    /// than leaving the fight unwinnable. The recovery is deliberately minimal: clamp
    /// back inside the arena, drop the velocity, and undo a kinematic body - a kinematic
    /// rigidbody ignores gravity entirely, which is the one way an upward velocity never
    /// comes back down.
    /// </summary>
    internal class BossLeash : MonoBehaviour
    {
        /// <summary>How far outside the arena counts as gone.</summary>
        private const float Margin = 12f;
        private const float Interval = 0.5f;

        private float _next;
        private int _reported;
        private Rigidbody2D _body;

        private void Start()
        {
            _body = GetComponent<Rigidbody2D>();
            _next = Time.time + Interval;
        }

        private void Update()
        {
            if (Time.time < _next) return;
            _next = Time.time + Interval;

            GameManager gm = GameManager.instance;
            if (gm == null || gm.sceneWidth <= 0f || gm.sceneHeight <= 0f) return;

            Vector3 p = transform.position;
            float minX = -Margin, maxX = gm.sceneWidth + Margin;
            float minY = -Margin, maxY = gm.sceneHeight + Margin;
            if (p.x >= minX && p.x <= maxX && p.y >= minY && p.y <= maxY) return;

            if (_reported < 3)
            {
                _reported++;
                string body = _body == null
                    ? "no rigidbody"
                    : $"{_body.bodyType}, gravity {_body.gravityScale}, v {_body.linearVelocity}";
                Plugin.Log.LogWarning(
                    $"Godhome: '{name}' left the arena at {p} (bounds " +
                    $"{gm.sceneWidth} x {gm.sceneHeight}) - {body}\n" +
                    "  states: " + States());
            }

            transform.position = new Vector3(
                Mathf.Clamp(p.x, 2f, gm.sceneWidth - 2f),
                Mathf.Clamp(p.y, 2f, gm.sceneHeight - 2f),
                p.z);

            if (_body != null)
            {
                // A kinematic body ignores gravity, so an upward velocity never returns.
                if (_body.bodyType == RigidbodyType2D.Kinematic)
                    _body.bodyType = RigidbodyType2D.Dynamic;
                _body.linearVelocity = Vector2.zero;
            }
        }

        private string States()
        {
            var sb = new System.Text.StringBuilder();
            foreach (PlayMakerFSM f in GetComponents<PlayMakerFSM>())
            {
                if (f == null) continue;
                if (sb.Length > 0) sb.Append(", ");
                string s;
                try { s = f.ActiveStateName; }
                catch (System.Exception) { s = "?"; }
                sb.Append(f.FsmName).Append('=').Append(s);
            }
            return sb.Length > 0 ? sb.ToString() : "(no FSMs)";
        }
    }
}
