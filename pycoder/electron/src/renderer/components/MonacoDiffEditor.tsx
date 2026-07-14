/** Monaco DiffEditor — visual diff comparison panel */
import React, { useCallback, useRef } from 'react';
import { DiffEditor, loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';

loader.config({ monaco });

interface Props {
    original: string;
    modified: string;
    language: string;
    filePath: string;
    onAcceptAll?: () => void;
    onAcceptSelected?: (ranges: monaco.editor.ILineRange[]) => void;
    onRevertAll?: () => void;
}

export const MonacoDiffEditor: React.FC<Props> = ({
    original, modified, language, filePath,
    onAcceptAll, onAcceptSelected, onRevertAll,
}) => {
    const diffRef = useRef<monaco.editor.IStandaloneDiffEditor>(null);

    const handleMount = useCallback((editor: monaco.editor.IStandaloneDiffEditor) => {
        diffRef.current = editor;
        editor.updateOptions({
            fontSize: 13,
            fontFamily: "'Cascadia Code','Fira Code',monospace",
            minimap: { enabled: false },
            renderSideBySide: true,
            readOnly: false,
        });
    }, []);

    return (
        <div className="monaco-diff-container">
            <div className="monaco-diff-header">
                <span className="diff-file-name">{filePath}</span>
                <div className="diff-actions">
                    <button className="diff-btn diff-btn-apply" onClick={onAcceptAll}>✅ Accept All</button>
                    <button className="diff-btn diff-btn-revert" onClick={onRevertAll}>↩ Revert All</button>
                </div>
            </div>
            <div className="monaco-diff-editor">
                <DiffEditor
                    height="100%"
                    language={language}
                    original={original}
                    modified={modified}
                    onMount={handleMount}
                    theme="vs-dark"
                />
            </div>
        </div>
    );
};
