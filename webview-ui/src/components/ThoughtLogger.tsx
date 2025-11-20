import React from 'react';

interface ThoughtLoggerProps {
  thought_trace?: string;
  active_model?: string;
  mode?: 'planning' | 'reflecting' | 'idle' | string;
}

export const ThoughtLogger: React.FC<ThoughtLoggerProps> = ({
  thought_trace = '',
  active_model = 'unknown',
  mode = 'idle',
}) => {
  const animating = mode === 'planning' || mode === 'reflecting';

  return (
    <div className="thought-logger">
      <style>{`
.thought-logger { font-family: Inter, Arial, sans-serif; margin: 8px 0; }
.accordion { border: 1px solid var(--border, #e5e7eb); border-radius: 8px; overflow: hidden; background: var(--card-bg,#fff); }
summary { list-style: none; cursor: pointer; padding: 10px 12px; display:flex; align-items:center; gap:8px; font-weight:600; background: linear-gradient(90deg, rgba(255,255,255,0.02), rgba(0,0,0,0)); }
details[open] summary { border-bottom: 1px solid var(--border,#e5e7eb); }
.brain { font-size:18px; display:inline-block; transition: transform .2s ease-in-out; }
.brain.animate { animation: brain-pulse 1s ease-in-out infinite; transform-origin: center; }
@keyframes brain-pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.12) rotate(-6deg); }
  100% { transform: scale(1); }
}
.badge { margin-left:auto; padding:4px 8px; border-radius:999px; background:#eef2ff; color:#3730a3; font-size:12px; border:1px solid #e0e7ff; }
.content { padding: 12px; }
.thought-trace { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, "Roboto Mono", "Courier New", monospace; white-space: pre-wrap; background: var(--muted-bg,#f8fafc); padding:10px; border-radius:6px; border:1px solid #eef2f6; font-size:13px; color:#0f172a; }
.empty { color:#6b7280; font-size:13px; }
`}</style>

      <details className="accordion">
        <summary>
          <span className={`brain ${animating ? 'animate' : ''}`} role="img" aria-label="brain">🧠</span>
          <span>Reasoning Process</span>
          <span className="badge" title={`Active model: ${active_model}`}>{active_model}</span>
        </summary>
        <div className="content">
          {thought_trace ? (
            <pre className="thought-trace">{thought_trace}</pre>
          ) : (
            <div className="empty">No reasoning trace available.</div>
          )}
        </div>
      </details>
    </div>
  );
};

export default ThoughtLogger;