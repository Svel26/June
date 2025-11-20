import React from "react";
import { SandpackProvider, SandpackLayout, SandpackPreview } from "@codesandbox/sandpack-react";

type Props = {
  files: Record<string, string>;
};

const defaultFiles: Record<string, string> = {
  "/index.html": `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Live Preview</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>`,
  "/index.js": `import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
const root = createRoot(document.getElementById("root"));
root.render(<App />);`,
  "/App.js": `import React from "react";
export default function App() {
  return <div style={{ padding: 20 }}>Live Preview</div>;
}`,
};

const LivePreview: React.FC<Props> = ({ files }) => {
  const mergedFiles = { ...defaultFiles, ...files };

  return (
    <SandpackProvider template="react" files={mergedFiles} theme="dark">
      <SandpackLayout>
        <SandpackPreview />
        {/* SandpackCodeEditor intentionally hidden for now */}
      </SandpackLayout>
    </SandpackProvider>
  );
};

export default LivePreview;