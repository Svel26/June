import React from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { materialLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

type Artifact = {
  type: 'code' | 'markdown' | string;
  filename?: string;
  code?: string;
  language?: string;
  markdown?: string;
};

export interface ArtifactRendererProps {
  artifact: Artifact;
}

const containerStyle: React.CSSProperties = {
  border: '1px solid #e6eef6',
  borderRadius: 6,
  padding: 12,
  background: '#ffffff',
  fontFamily: 'Inter,Segoe UI,Roboto,system-ui,-apple-system',
  boxShadow: '0 1px 2px rgba(16,24,40,0.04)'
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  marginBottom: 8
};

const filenameStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: '#0f172a'
};

const ArtifactRenderer: React.FC<ArtifactRendererProps> = ({ artifact }) => {
  const renderCode = () => {
    const filename = artifact.filename || 'untitled';
    const code = artifact.code ?? '';
    const language = (artifact.language as any) ?? 'text';

    return (
      <div style={containerStyle}>
        <div style={headerStyle}>
          <div style={filenameStyle}>{filename}</div>
        </div>
        <SyntaxHighlighter
          language={language}
          style={materialLight}
          showLineNumbers
          wrapLongLines
          customStyle={{ borderRadius: 4, padding: 12, fontSize: 12 }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    );
  };

  const renderMarkdown = () => {
    const md = artifact.markdown ?? '';
    return (
      <div style={containerStyle}>
        <div style={headerStyle}>
          <div style={filenameStyle}>Markdown</div>
        </div>
        <div style={{ color: '#0f172a', fontSize: 13, lineHeight: 1.4, whiteSpace: 'pre-wrap' }}>
          {md}
        </div>
      </div>
    );
  };

  switch (artifact.type) {
    case 'code':
      return renderCode();
    case 'markdown':
      return renderMarkdown();
    default:
      return (
        <div style={containerStyle}>
          <div style={filenameStyle}>Unsupported artifact type: {String(artifact.type)}</div>
        </div>
      );
  }
};

export default ArtifactRenderer;