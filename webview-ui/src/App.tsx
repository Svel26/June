import React, { useEffect, useState } from 'react';
import PlanViewer from './PlanViewer';
import ArtifactRenderer from './components/ArtifactRenderer';
import ApprovalCard from './components/ApprovalCard';
import ThoughtLogger from './components/ThoughtLogger';
import LivePreview from './components/LivePreview';
import './App.css';
 
type WebviewData = {
  prompt?: string;
  plan?: string[];
  currentStepIndex?: number;
  artifacts?: any[];
  next?: string;
  taskId?: string;
  proposedToolCall?: string;
  thought_trace?: string;
  active_model?: string;
};
 
export default function App() {
  const [data, setData] = useState<WebviewData>({
    prompt: '',
    plan: [],
    currentStepIndex: 0,
    artifacts: [],
    next: undefined,
    taskId: undefined,
    proposedToolCall: undefined,
  });
 
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      // Accept either { prompt, plan, currentStepIndex, next, taskId, proposedToolCall } or { type: '...', data: { ... } }
      const raw = event.data ?? {};
      const msg = raw.data ?? raw;
      setData((prev) => ({
        ...prev,
        prompt:
          typeof msg.prompt === 'string'
            ? msg.prompt
            : typeof raw.prompt === 'string'
            ? raw.prompt
            : prev.prompt,
        plan: Array.isArray(msg.plan) ? msg.plan : Array.isArray(raw.plan) ? raw.plan : prev.plan,
        currentStepIndex:
          typeof msg.currentStepIndex === 'number'
            ? msg.currentStepIndex
            : typeof raw.currentStepIndex === 'number'
            ? raw.currentStepIndex
            : prev.currentStepIndex,
        artifacts: Array.isArray(msg.artifacts)
          ? msg.artifacts
          : Array.isArray(raw.artifacts)
          ? raw.artifacts
          : prev.artifacts,
        // new: detect paused/interrupted state info that may come in the polling messages
        next: typeof msg.next === 'string' ? msg.next : typeof raw.next === 'string' ? raw.next : prev.next,
        taskId: typeof msg.taskId === 'string' ? msg.taskId : typeof raw.taskId === 'string' ? raw.taskId : prev.taskId,
        proposedToolCall:
          typeof msg.proposedToolCall === 'string'
            ? msg.proposedToolCall
            : typeof raw.proposedToolCall === 'string'
            ? raw.proposedToolCall
            : // some messages may include a proposedAction or tool call inside artifacts; try to extract a simple representation
            Array.isArray(msg.artifacts) && msg.artifacts[0] && typeof msg.artifacts[0].call === 'string'
            ? msg.artifacts[0].call
            : Array.isArray(raw.artifacts) && raw.artifacts[0] && typeof raw.artifacts[0].call === 'string'
            ? raw.artifacts[0].call
            : prev.proposedToolCall,
        thought_trace:
          typeof msg.thought_trace === 'string'
            ? msg.thought_trace
            : typeof raw.thought_trace === 'string'
            ? raw.thought_trace
            : prev.thought_trace,
        active_model:
          typeof msg.active_model === 'string'
            ? msg.active_model
            : typeof raw.active_model === 'string'
            ? raw.active_model
            : prev.active_model,
      }));
    };
 
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);
 
  // helper: whether agent is paused waiting for approval
  const isPausedForApproval = (next?: string) => {
    // per instructions: paused/interrupted state in the polling loop when `next` includes "executor"
    return typeof next === 'string' && next.toLowerCase().includes('executor');
  };
 
  const handleApprove = async () => {
    if (!data.taskId) {
      // notify host if taskId missing
      window.postMessage({ type: 'approval:error', data: { message: 'taskId missing for approval' } }, '*');
      return;
    }
    try {
      await fetch(`/task/${encodeURIComponent(data.taskId)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: true }),
      });
      window.postMessage({ type: 'approval:approved', data: { taskId: data.taskId } }, '*');
    } catch (err) {
      window.postMessage({ type: 'approval:error', data: { message: String(err) } }, '*');
    }
  };
 
  const handleReject = async (feedback: string) => {
    if (!data.taskId) {
      window.postMessage({ type: 'approval:error', data: { message: 'taskId missing for rejection' } }, '*');
      return;
    }
    try {
      await fetch(`/task/${encodeURIComponent(data.taskId)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: false, feedback }),
      });
      window.postMessage({ type: 'approval:rejected', data: { taskId: data.taskId, feedback } }, '*');
    } catch (err) {
      window.postMessage({ type: 'approval:error', data: { message: String(err) } }, '*');
    }
  };
 
  // Aggregate artifacts into a Sandpack-ready files map (only from agent-provided artifacts)
  const sandpackFilesFromArtifacts: Record<string, string> = (Array.isArray(data.artifacts) ? data.artifacts : []).reduce<
    Record<string, string>
  >((acc, art) => {
    const filename = typeof (art && (art.filename as any)) === 'string' ? (art.filename as string) : '';
    const code = typeof (art && (art.code as any)) === 'string' ? (art.code as string) : '';

    if (!filename) return acc;
    const path = filename.startsWith('/') ? filename : `/${filename}`;
    acc[path] = code;
    return acc;
  }, {});

  // UI tab state: default to 'preview' if the agent already created App.tsx or index.html; otherwise 'code'
  const [selectedTab, setSelectedTab] = useState<'code' | 'preview'>(() => {
    const hasAgentEntry = Object.keys(sandpackFilesFromArtifacts).some((k) =>
      k.endsWith('App.tsx') || k.endsWith('/App.tsx') || k.endsWith('index.html') || k.endsWith('/index.html')
    );
    return hasAgentEntry ? 'preview' : 'code';
  });

  // If the agent later creates App.tsx or index.html, auto-switch to preview
  useEffect(() => {
    const hasAgentEntry = Object.keys(sandpackFilesFromArtifacts).some((k) =>
      k.endsWith('App.tsx') || k.endsWith('/App.tsx') || k.endsWith('index.html') || k.endsWith('/index.html')
    );
    if (hasAgentEntry) {
      setSelectedTab('preview');
    }
    // Intentionally only depend on data.artifacts to detect new files
  }, [data.artifacts]);

  // Build final sandpackFiles including fallback skeletons so LivePreview/Sandpack never crashes
  const sandpackFiles: Record<string, string> = { ...sandpackFilesFromArtifacts };

  // Ensure minimal entry points so Sandpack won't crash if the agent hasn't written a full app yet
  if (!Object.keys(sandpackFiles).some((k) => k.endsWith('App.tsx') || k.endsWith('/App.tsx') || k.endsWith('App.jsx') || k.endsWith('App.js'))) {
    sandpackFiles['/App.tsx'] = `import React from 'react';
export default function App() {
  return <div style={{ padding: 20 }}>App skeleton</div>;
}`;
  }

  if (!Object.keys(sandpackFiles).some((k) => k.endsWith('index.tsx') || k.endsWith('/index.tsx') || k.endsWith('index.jsx') || k.endsWith('index.js'))) {
    sandpackFiles['/index.tsx'] = `import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
const root = createRoot(document.getElementById('root'));
root.render(<App />);`;
  }

  if (!Object.prototype.hasOwnProperty.call(sandpackFiles, '/index.html')) {
    sandpackFiles['/index.html'] = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Live Preview</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>`;
  }

  return (
    <div className="app-root">
      <header className="app-header">
        <h1>OSA E IDE — Webview UI</h1>
        <button
          title="Clear tasks"
          onClick={() => {
            const vscode = (window as any).acquireVsCodeApi?.();
            vscode?.postMessage?.({ type: 'osae.reset' });
          }}
          style={{
            marginLeft: 12,
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            fontSize: 18,
          }}
        >
          🗑️
        </button>
      </header>

      <main className="app-main">
        <section className="prompt">
          <h2>User prompt</h2>
          <div className="prompt-content">
            {data.prompt ? <span>{data.prompt}</span> : <em>No prompt received</em>}
          </div>
        </section>

        <section className="thought-logger">
          <ThoughtLogger thought_trace={data.thought_trace || ''} active_model={data.active_model || 'unknown'} />
        </section>

        <section className="plan">
          <h2>Execution plan</h2>
          <PlanViewer plan={data.plan || []} currentStepIndex={data.currentStepIndex || 0} />
        </section>

        {/* Approval UI: shown when polling indicates executor pause */}
        {isPausedForApproval(data.next) && (
          <section className="approval" style={{ marginTop: 16 }}>
            <ApprovalCard
              proposedAction={data.proposedToolCall || 'Proposed tool call not available'}
              onApprove={handleApprove}
              onReject={handleReject}
              visible={true}
            />
          </section>
        )}

        <section className="artifacts">
          <h2>Artifacts & Preview</h2>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              onClick={() => setSelectedTab('code')}
              style={{
                padding: '6px 10px',
                borderRadius: 4,
                border: selectedTab === 'code' ? '1px solid #333' : '1px solid #ccc',
                background: selectedTab === 'code' ? '#eee' : 'transparent',
                cursor: 'pointer',
              }}
            >
              Code
            </button>
            <button
              onClick={() => setSelectedTab('preview')}
              style={{
                padding: '6px 10px',
                borderRadius: 4,
                border: selectedTab === 'preview' ? '1px solid #333' : '1px solid #ccc',
                background: selectedTab === 'preview' ? '#eee' : 'transparent',
                cursor: 'pointer',
              }}
            >
              Preview
            </button>
          </div>
 
          {selectedTab === 'code' ? (
            <div className="artifacts-list" style={{ marginTop: 12 }}>
              {Array.isArray(data.artifacts) && data.artifacts.length > 0 ? (
                data.artifacts.map((artifact, idx) => (
                  <div key={idx} style={{ marginBottom: 12 }}>
                    <ArtifactRenderer artifact={artifact} />
                  </div>
                ))
              ) : (
                <em>No artifacts received</em>
              )}
            </div>
          ) : (
            <div style={{ marginTop: 12 }}>
              <LivePreview files={sandpackFiles} />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}