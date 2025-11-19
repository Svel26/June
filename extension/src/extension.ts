import * as vscode from 'vscode';
import { spawn, spawnSync, ChildProcess } from 'child_process';
import * as path from 'path';

const outputChannel = vscode.window.createOutputChannel('OSAE');
let pythonProcess: ChildProcess | undefined;
let dashboardPanel: vscode.WebviewPanel | undefined;

/**
 * Spawn the Python FastAPI sidecar:
 * Command: python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
 * Working directory: osae-ide/agent-server (relative to the extension root)
 */
function spawnPythonServer(context: vscode.ExtensionContext): ChildProcess | undefined {
    try {
        const agentServerPath = path.join(context.extensionPath, '..', 'agent-server');

        // Try a list of candidate python launchers and pick the first that responds to `--version`.
        const candidates = process.platform === 'win32' ? ['py', 'python', 'python3'] : ['python3', 'python'];
        let pythonCmd: string | undefined;
        for (const candidate of candidates) {
            try {
                const check = spawnSync(candidate, ['--version'], { stdio: 'ignore' });
                if (check && typeof (check as any).status === 'number' && (check as any).status === 0) {
                    pythonCmd = candidate;
                    break;
                }
            } catch (e) {
                // ignore and try next candidate
            }
        }

        if (!pythonCmd) {
            outputChannel.appendLine('[OSAE] No usable Python executable found in PATH; sidecar will not start.');
            return undefined;
        }

        const proc = spawn(pythonCmd, ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], {
            cwd: agentServerPath,
            stdio: ['ignore', 'pipe', 'pipe']
        });

        pythonProcess = proc;

        outputChannel.appendLine(`[OSAE] Python FastAPI sidecar spawned using "${pythonCmd}" (PID ${proc.pid}).`);
        outputChannel.show(true);

        proc.stdout?.on('data', (chunk: Buffer) => {
            const text = chunk.toString().trim();
            if (text) outputChannel.appendLine(`[Python stdout] ${text}`);
        });

        proc.stderr?.on('data', (chunk: Buffer) => {
            const text = chunk.toString().trim();
            if (text) outputChannel.appendLine(`[Python stderr] ${text}`);
        });

        proc.on('exit', (code, signal) => {
            outputChannel.appendLine(`[OSAE] Python process exited with code=${code} signal=${signal}`);
        });

        return proc;
    } catch (err) {
        outputChannel.appendLine(`[OSAE] Failed to spawn Python server: ${err}`);
        return undefined;
    }
}

async function pollHealthEndpoint() {
    const url = 'http://127.0.0.1:8000/health';
    try {
        // Use global fetch if available; cast to any to avoid TS DOM types dependency.
        const fetchFn = (globalThis as any).fetch;
        if (typeof fetchFn !== 'function') {
            outputChannel.appendLine('[OSAE] fetch is not available in this environment; skipping health check.');
            return;
        }

        const res = await fetchFn(url, { method: 'GET' });
        if (res && res.ok) {
            outputChannel.appendLine(`[OSAE] Health check succeeded (status ${res.status}) at ${url}`);
        } else {
            const status = res ? res.status : 'no-response';
            outputChannel.appendLine(`[OSAE] Health check failed (status ${status}) at ${url}`);
        }
    } catch (err) {
        outputChannel.appendLine(`[OSAE] Health check error: ${err}`);
    }
}

/**
 * Return HTML for the webview that loads the built React app (index.js / index.css)
 * from the extension's media folder.
 *
 * - Uses vscode.Uri.joinPath and webview.asWebviewUri to build correct URIs
 * - Updates Content-Security-Policy to allow scripts and styles from webview.cspSource
 */
function getWebviewContent(context: vscode.ExtensionContext, webview: vscode.Webview): string {
    const mediaFolder = vscode.Uri.joinPath(context.extensionUri, 'media');
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaFolder, 'index.js'));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaFolder, 'index.css'));
    const cspSource = webview.cspSource;

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource} https:; connect-src ${cspSource} http://127.0.0.1:8000; script-src ${cspSource}; style-src ${cspSource};">
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OSAE Dashboard</title>
  <link rel="stylesheet" href="${styleUri}">
</head>
<body>
  <div id="root"></div>
  <script src="${scriptUri}"></script>
</body>
</html>`;
}

export function activate(context: vscode.ExtensionContext) {
    outputChannel.appendLine('[OSAE] Activating extension and starting orchestration.');

    // Spawn Python server and keep reference for cleanup
    pythonProcess = spawnPythonServer(context);

    // Ensure we attempt health check 2 seconds after starting the process
    setTimeout(() => {
        if (pythonProcess) {
            pollHealthEndpoint();
        } else {
            outputChannel.appendLine('[OSAE] Python process not available; skipping health check.');
        }
    }, 2000);

    // Register command to open dashboard WebviewPanel
    const openDashboard = vscode.commands.registerCommand('osae.openDashboard', () => {
        if (dashboardPanel) {
            dashboardPanel.reveal(vscode.ViewColumn.One);
            return;
        }
        dashboardPanel = vscode.window.createWebviewPanel(
            'osaeDashboard',
            'OSAE Dashboard',
            vscode.ViewColumn.One,
            {
                enableScripts: true,
                localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')]
            }
        );
        // Load the built React app from the extension's media folder
        dashboardPanel.webview.html = getWebviewContent(context, dashboardPanel.webview);
        dashboardPanel.onDidDispose(() => {
            dashboardPanel = undefined;
        });
    });
    context.subscriptions.push(openDashboard);

    // Register command to start a task via the sidecar API and poll for updates
    const startCommand = vscode.commands.registerCommand('osae.start', async () => {
        // Ensure dashboard is open
        if (!dashboardPanel) {
            await vscode.commands.executeCommand('osae.openDashboard');
        }
        const panel = dashboardPanel!;

        // Always attempt to use the real backend at 127.0.0.1:8000 first.
        // Only fall back to the local simulated task when the server is unreachable
        // (network error, connection refused or timeout). Simulation is therefore
        // strictly an error-path fallback, not the default.
        const fetchFn = (globalThis as any).fetch;
        if (typeof fetchFn !== 'function') {
            outputChannel.appendLine('[OSAE] fetch is not available; cannot start task.');
            return;
        }
    
        // Helper to start a simulated task (used only on network failure)
        const startSimulatedTask = () => {
            outputChannel.appendLine('[OSAE] Starting simulated task for UI verification (fallback).');
            const simulatedPlan = ['Gather context', 'Plan actions', 'Execute steps'];
            const simTaskId = `sim-${Date.now()}`;
            panel.webview.postMessage({ type: 'task_started', task_id: simTaskId, prompt: 'Simulated run' });
            panel.webview.postMessage({ type: 'task_update', data: { plan: simulatedPlan, currentStepIndex: 0 } });
    
            let idx = 0;
            const simInterval = setInterval(() => {
                idx++;
                panel.webview.postMessage({ type: 'task_update', data: { plan: simulatedPlan, currentStepIndex: idx } });
                outputChannel.appendLine(`[OSAE] Simulated task ${simTaskId} progress: step ${idx}`);
    
                if (idx >= simulatedPlan.length - 1) {
                    panel.webview.postMessage({ type: 'task_update', data: { plan: simulatedPlan, currentStepIndex: idx, status: 'completed', task_status: 'completed', state: 'completed' } });
                    outputChannel.appendLine(`[OSAE] Simulated task ${simTaskId} completed; stopping simulated poll.`);
                    clearInterval(simInterval);
                }
            }, 1000);
        };
    
        try {
            // POST /task to create a new task with a short timeout — if the server is unreachable
            // this should throw and we will fall back to simulation.
            const controller = new AbortController();
            const timeoutMs = 3000;
            const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);
    
            const res = await fetchFn('http://127.0.0.1:8000/task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
                signal: controller.signal
            });
            clearTimeout(timeoutHandle);
    
            if (!res || !res.ok) {
                outputChannel.appendLine(`[OSAE] Failed to create task (status ${res ? res.status : 'no-response'})`);
                return;
            }
    
            const data = await res.json();
            const taskId = data.task_id || data.id || data.taskId;
            if (!taskId) {
                outputChannel.appendLine('[OSAE] POST /task did not return a task_id.');
                return;
            }
    
            outputChannel.appendLine(`[OSAE] Started task: ${taskId}`);
            let currentTaskId = taskId;
    
            // Notify webview that task started
            panel.webview.postMessage({ type: 'task_started', task_id: currentTaskId });
    
            // Polling loop every 1000ms
            const interval = setInterval(async () => {
                try {
                    const r = await fetchFn(`http://127.0.0.1:8000/task/${encodeURIComponent(currentTaskId)}`, { method: 'GET' });
                    if (!r) {
                        outputChannel.appendLine(`[OSAE] No response polling task ${currentTaskId}`);
                        return;
                    }
                    const json = await r.json();
                    // Post the JSON result to the Webview
                    panel.webview.postMessage({ type: 'task_update', data: json });
    
                    // Stop polling when task is completed
                    if (json.task_status === 'completed' || json.status === 'completed' || json.state === 'completed') {
                        outputChannel.appendLine(`[OSAE] Task ${currentTaskId} completed; stopping poll.`);
                        clearInterval(interval);
                    }
                } catch (err) {
                    outputChannel.appendLine(`[OSAE] Error polling task ${currentTaskId}: ${err}`);
                }
            }, 1000);
        } catch (err: any) {
            // Determine if error is a network/connect/timeout issue — only then fall back to simulation.
            const msg = (err && err.message) ? String(err.message) : String(err);
            const isNetworkError = err && (err.name === 'AbortError' || /ECONNREFUSED|connect|failed to fetch|NetworkError/i.test(msg));
            outputChannel.appendLine(`[OSAE] Error creating task: ${err}`);
            if (isNetworkError) {
                outputChannel.appendLine('[OSAE] Server unreachable — falling back to simulated task.');
                startSimulatedTask();
            } else {
                outputChannel.appendLine('[OSAE] Server returned an error; not falling back to simulation.');
            }
        }
    });
    context.subscriptions.push(startCommand);

    // Add a disposable to context so the output channel is disposed when extension deactivates
    context.subscriptions.push(outputChannel);
}

export function deactivate() {
    outputChannel.appendLine('[OSAE] Deactivating extension; cleaning up resources.');
    if (pythonProcess) {
        try {
            pythonProcess.kill();
            outputChannel.appendLine(`[OSAE] Killed Python process (PID ${pythonProcess.pid}).`);
        } catch (err) {
            outputChannel.appendLine(`[OSAE] Error killing Python process: ${err}`);
        }
        pythonProcess = undefined;
    } else {
        outputChannel.appendLine('[OSAE] No Python process to kill.');
    }
}