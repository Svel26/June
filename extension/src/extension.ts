import * as vscode from 'vscode';
import { spawn, spawnSync, ChildProcess } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

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
        const agentServerPath = path.join(context.extensionPath, 'agent-server');
 
        // Use the Python interpreter from the extension's bundled venv.
        // On Windows: venv\Scripts\python.exe
        // On Unix:   venv/bin/python
        const pythonExe = path.join(
            agentServerPath,
            'venv',
            process.platform === 'win32' ? 'Scripts' : 'bin',
            process.platform === 'win32' ? 'python.exe' : 'python'
        );
 
        // Always use the venv interpreter — never fall back to system Python.
        let pythonCmd: string = pythonExe;
        try {
            const check = spawnSync(pythonExe, ['--version'], { stdio: 'ignore' });
            if (!check || typeof (check as any).status !== 'number' || (check as any).status !== 0) {
                throw new Error(`venv python not found or not executable at ${pythonExe}`);
            }
        } catch (e) {
            outputChannel.appendLine(`[OSAE] venv Python executable not found or not usable at "${pythonExe}": ${e}`);
            // Fail loudly — do not attempt to fall back to system Python.
            throw e;
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

/**
 * Ensure the bundled agent-server venv exists; if missing, run the platform-appropriate setup script
 * and await its completion before continuing. Shows a user-facing progress notification while running.
 */
async function ensureAgentServerSetup(context: vscode.ExtensionContext): Promise<void> {
    const agentServerPath = path.join(context.extensionPath, 'agent-server');
    const pythonExe = path.join(
        agentServerPath,
        'venv',
        process.platform === 'win32' ? 'Scripts' : 'bin',
        process.platform === 'win32' ? 'python.exe' : 'python'
    );

    if (fs.existsSync(pythonExe)) {
        outputChannel.appendLine(`[OSAE] Found bundled venv Python at ${pythonExe}`);
        return;
    }

    outputChannel.appendLine('[OSAE] Bundled venv Python not found; running initial setup.');

    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'OSAE: Initializing AI Runtime...',
        cancellable: false
    }, (progress) => {
        return new Promise<void>((resolve, reject) => {
            const scriptName = process.platform === 'win32' ? 'setup_agent_server.ps1' : 'setup_agent_server.sh';
            const scriptPath = path.join(context.extensionPath, 'scripts', scriptName);

            outputChannel.appendLine(`[OSAE] Running setup script: ${scriptPath}`);

            let cmd: string;
            let args: string[];

            if (process.platform === 'win32') {
                // Use powershell to run the setup script
                cmd = 'powershell.exe';
                args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptPath];
            } else {
                // Use bash/sh to run the script on Unix-like systems
                cmd = 'bash';
                args = [scriptPath];
            }

            const child = spawn(cmd, args, { cwd: context.extensionPath, stdio: ['ignore', 'pipe', 'pipe'] });

            let stdout = '';
            let stderr = '';

            child.stdout?.on('data', (c: Buffer) => {
                const text = c.toString();
                stdout += text;
                outputChannel.appendLine(`[setup stdout] ${text.trim()}`);
            });
            child.stderr?.on('data', (c: Buffer) => {
                const text = c.toString();
                stderr += text;
                outputChannel.appendLine(`[setup stderr] ${text.trim()}`);
            });

            child.on('error', (err) => {
                outputChannel.appendLine(`[OSAE] Failed to spawn setup script: ${err}`);
                vscode.window.showErrorMessage('[OSAE] Failed to start AI runtime setup. See OSAE output for details.');
                reject(err);
            });

            child.on('close', (code) => {
                if (code === 0) {
                    outputChannel.appendLine('[OSAE] Agent server setup completed successfully.');
                    // Quick sanity check: pythonExe should now exist
                    if (!fs.existsSync(pythonExe)) {
                        outputChannel.appendLine(`[OSAE] Setup finished but venv python still missing at ${pythonExe}`);
                        vscode.window.showErrorMessage('[OSAE] Setup completed but bundled Python not found. See OSAE output.');
                        reject(new Error('venv python missing after setup'));
                        return;
                    }
                    resolve();
                } else {
                    outputChannel.appendLine(`[OSAE] Agent server setup failed with code ${code}. Stderr:\n${stderr}`);
                    vscode.window.showErrorMessage(`[OSAE] AI runtime setup failed. See OSAE output for details.`);
                    reject(new Error(stderr || `setup exited with code ${code}`));
                }
            });
        });
    });
}

export async function activate(context: vscode.ExtensionContext) {
    outputChannel.appendLine('[OSAE] Activating extension and starting orchestration.');

    // Ensure the agent-server venv exists; if not, run first-run setup and wait for completion.
    try {
        await ensureAgentServerSetup(context);
    } catch (err: any) {
        outputChannel.appendLine(`[OSAE] Agent server setup failed: ${err}`);
        // err may contain stderr text; include a short snippet in the shown message
        const detail = (err && err.message) ? err.message : String(err);
        vscode.window.showErrorMessage(`[OSAE] Failed to initialize AI runtime: ${detail}`);
        // Do not proceed to spawn the Python server if setup failed
        return;
    }

    // Spawn Python server and keep reference for cleanup (use venv interpreter; fail loudly on error)
    try {
        pythonProcess = spawnPythonServer(context);
    } catch (err) {
        outputChannel.appendLine(`[OSAE] Failed to start Python sidecar: ${err}`);
        vscode.window.showErrorMessage('[OSAE] Failed to start Python sidecar. See OSAE output for details.');
        pythonProcess = undefined;
    }

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
        // Handle messages from the Webview
        dashboardPanel.webview.onDidReceiveMessage(async (msg) => {
            if (msg && msg.type === 'osae.reset') {
                try {
                    await vscode.commands.executeCommand('osae.reset');
                } catch (err) {
                    outputChannel.appendLine(`[OSAE] Error executing osae.reset command: ${err}`);
                }
            }
        });
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
    
        // Simulation fallback removed — extension must use the real Python sidecar (venv).
    
        try {
            // POST /task to create a new task with a short timeout — if the server is unreachable
            // this should throw and we will fall back to simulation.
            const controller = new AbortController();
            const timeoutMs = 3000;
            const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);
    
            const res = await fetchFn('http://127.0.0.1:8000/task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: '' }),
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
            // Fail loudly on any error when interacting with the real sidecar — do not simulate.
            outputChannel.appendLine(`[OSAE] Error creating task: ${err}`);
            vscode.window.showErrorMessage(`[OSAE] Failed to create task: ${err}`);
            return;
        }
    });
    context.subscriptions.push(startCommand);

    // Register command to reset TASK_STORE via sidecar API and refresh the dashboard webview
    const resetCommand = vscode.commands.registerCommand('osae.reset', async () => {
        const fetchFn = (globalThis as any).fetch;
        if (typeof fetchFn !== 'function') {
            outputChannel.appendLine('[OSAE] fetch is not available; cannot perform reset.');
            return;
        }
        try {
            const res = await fetchFn('http://127.0.0.1:8000/reset', { method: 'POST' });
            if (!res || !res.ok) {
                outputChannel.appendLine(`[OSAE] Reset request failed (status ${res ? res.status : 'no-response'})`);
                return;
            }
            outputChannel.appendLine('[OSAE] TASK_STORE reset via sidecar.');
            // Refresh webview if open
            if (dashboardPanel) {
                dashboardPanel.webview.html = getWebviewContent(context, dashboardPanel.webview);
            }
        } catch (err) {
            outputChannel.appendLine(`[OSAE] Error calling reset endpoint: ${err}`);
        }
    });
    context.subscriptions.push(resetCommand);

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