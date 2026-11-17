import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, Paperclip, Sparkles, X, FileText, ChevronDown } from 'lucide-react';
import { TONE_PRESETS, RESPONSE_LENGTHS } from '../../utils/constants';
import { isFileSupported, readFileAsText, formatFileSize } from '../../utils/fileProcessor';
import VoiceAssistant from '../VoiceAssistant/VoiceAssistant';
import PromptImprover from '../PromptImprover/PromptImprover';

export default function InputBar({ input, setInput, onSend, inputRef: suppliedRef, loading, attachedFile, setAttachedFile, attachedFiles = [], setAttachedFiles, setErr, voiceLanguage, onVoiceLanguageChange, tone, setTone, responseLength, setResponseLength }) {
  const localRef = useRef(null); const inputRef = suppliedRef || localRef; const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false); const [improver, setImprover] = useState(false);
  useEffect(() => { const open = () => setImprover(true); window.addEventListener('lyra:improve-prompt', open); return () => window.removeEventListener('lyra:improve-prompt', open); }, []);
  const files = [...(attachedFile ? [attachedFile] : []), ...attachedFiles];
  const addFile = async event => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file) return;
    if (!isFileSupported(file)) { setErr('That file type is not supported.'); return; }
    if (files.length >= 3) { setErr('You can attach up to three files.'); return; }
    setUploading(true);
    try { const content = await readFileAsText(file); const record = { id: crypto.randomUUID(), name: file.name, content, size: file.size }; if (!attachedFile) setAttachedFile(record); else setAttachedFiles(previous => [...previous, record]); }
    catch (error) { setErr(`Could not read the file: ${error.message}`); }
    finally { setUploading(false); }
  };
  const remove = file => { if (file === attachedFile) { setAttachedFile(attachedFiles[0] || null); setAttachedFiles(previous => previous.slice(1)); } else setAttachedFiles(previous => previous.filter(item => item !== file)); };
  return <div className="composer-region">{improver && <PromptImprover onApply={value => { setInput(value); setImprover(false); inputRef.current?.focus(); }} onClose={() => setImprover(false)} />}<div className="composer-card">{files.length > 0 && <div className="attachment-list">{files.map(file => <div className="attachment-chip" key={file.id || file.name}><FileText size={14} /><span>{file.name}<small>{formatFileSize(file.size)}</small></span><button aria-label={`Remove ${file.name}`} onClick={() => remove(file)}><X size={12} /></button></div>)}</div>}<textarea ref={inputRef} aria-label="Message Lyra" placeholder="Ask, create, or put a plan in motion…" value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!loading) onSend(); } }} rows={2} /><div className="composer-toolbar"><div className="composer-tools"><button className="composer-icon" aria-label="Attach file" title="Attach a document" disabled={uploading} onClick={() => fileRef.current?.click()}><Paperclip size={18} /></button><input hidden ref={fileRef} type="file" onChange={addFile} /><button className="composer-icon" aria-label="Improve prompt" title="Refine your prompt" onClick={() => setImprover(true)}><Sparkles size={17} /></button><span className="composer-tool-divider" /><label className="composer-select"><select aria-label="Response tone" value={tone} onChange={event => setTone(event.target.value)}>{TONE_PRESETS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select><ChevronDown size={11} /></label><label className="composer-select response-length"><select aria-label="Response length" value={responseLength.id} onChange={event => setResponseLength(RESPONSE_LENGTHS.find(item => item.id === event.target.value))}>{RESPONSE_LENGTHS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select><ChevronDown size={11} /></label></div><div className="composer-send-tools"><VoiceAssistant onTranscript={text => setInput(previous => previous ? previous + ' ' + text : text)} language={voiceLanguage} onLanguageChange={onVoiceLanguageChange} disabled={loading} /><button className="send-message" aria-label="Send message" title="Send message" disabled={loading || uploading || (!input.trim() && !files.length)} onClick={() => onSend()}><ArrowUp size={20} /></button></div></div></div><div className="composer-caption"><span>Actions request approval. Results leave a trace.</span><span><kbd>↵</kbd> send <i /> <kbd>⇧ ↵</kbd> new line</span></div></div>;
}
