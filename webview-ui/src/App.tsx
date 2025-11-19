import React, { useEffect, useState } from 'react';
import PlanViewer from './PlanViewer';
import ArtifactRenderer from './components/ArtifactRenderer';
import './App.css';

type WebviewData = {
  prompt?: string;
  plan?: string[];
  currentStepIndex?: number;
  artifacts?: any[];
};

export default function App() {
  const [data, setData] = useState<WebviewData>({
    prompt: '',
    plan: [],
    currentStepIndex: 0,
    artifacts: [],
  });

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      // Accept either { prompt, plan, currentStepIndex } or { type: '...', data: { ... } }
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
      }));
    };

    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  return (
    <div className="app-root">
      <header className="app-header">
        <h1>OSA E IDE — Webview UI</h1>
      </header>

      <main className="app-main">
        <section className="prompt">
          <h2>User prompt</h2>
          <div className="prompt-content">
            {data.prompt ? <span>{data.prompt}</span> : <em>No prompt received</em>}
          </div>
        </section>

        <section className="plan">
          <h2>Execution plan</h2>
          <PlanViewer plan={data.plan || []} currentStepIndex={data.currentStepIndex || 0} />
        </section>

        <section className="artifacts">
          <h2>Artifacts</h2>
          <div className="artifacts-list">
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
        </section>
      </main>
    </div>
  );
}