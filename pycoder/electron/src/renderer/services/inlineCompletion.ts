/**
 * Inline Completion Provider for Monaco Editor
 * Ghost text completion triggered on typing pause (500ms debounce)
 */
import type * as monaco from 'monaco-editor';
import { getWsUrl, getApiKey } from './config';

let _provider: monaco.IDisposable | null = null;

export function registerInlineCompletion(monacoInstance: typeof monaco): void {
    if (_provider) _provider.dispose();

    _provider = monacoInstance.languages.registerInlineCompletionsProvider(
        { pattern: '**' },
        {
            async provideInlineCompletions(
                model: monaco.editor.ITextModel,
                position: monaco.Position,
                _context: monaco.languages.InlineCompletionContext,
                _token: monaco.CancellationToken,
            ): Promise<monaco.languages.InlineCompletions<monaco.languages.InlineCompletion>> {
                // Lightweight completion: only prefix context (200 chars)
                const prefix = model.getValueInRange({
                    startLineNumber: Math.max(1, position.lineNumber - 5),
                    startColumn: 1,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column,
                });

                if (prefix.length < 10) return { items: [] };

                try {
                    const [baseUrl, apiKey] = await Promise.all([getWsUrl('/api/completion'), getApiKey()]);
                    const resp = await fetch(`${baseUrl}${apiKey ? '?api_key=' + encodeURIComponent(apiKey) : ''}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prefix, language: model.getLanguageId(), maxTokens: 30 }),
                        signal: AbortSignal.timeout(800),
                    });

                    if (!resp.ok) return { items: [] };
                    const data = await resp.json();
                    const completion = data.completion || data.text || '';
                    if (!completion || completion.length < 2) return { items: [] };

                    return {
                        items: [{ insertText: completion, range: new monacoInstance.Range(position.lineNumber, position.column, position.lineNumber, position.column) }],
                    };
                } catch {
                    return { items: [] };
                }
            },

            freeInlineCompletions() { },
        },
    );
}
