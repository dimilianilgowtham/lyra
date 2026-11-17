import React, { useState } from 'react';
import { ArrowUpRight, Plus, Search, MessageSquare, Terminal, PanelRight, ChevronDown, Trash2 } from 'lucide-react';
import { MODES } from '../../utils/constants';

export default function Sidebar({ user, activeMode, setActiveMode, chats, activeChatId, onNewChat, onSelectChat, onDeleteChat, sidebarOpen, onDesktop, onTasks }) {
  const [search, setSearch] = useState('');
  const visible = chats.filter(chat => (chat.title || '').toLowerCase().includes(search.toLowerCase()));
  return <aside className={`workspace-sidebar ${sidebarOpen ? '' : 'is-collapsed'}`} aria-label="Workspace navigation">
    <a className="brand" href="#" onClick={event => { event.preventDefault(); onNewChat(); }} aria-label="Lyra home"><span className="brand-symbol" aria-hidden="true">✳</span><span>lyra<span className="brand-period">.</span></span><span className="brand-version">DESKTOP</span></a>
    <button className="new-conversation" onClick={onNewChat}><Plus size={17} />New conversation<span>⌘ N</span></button>
    <nav className="primary-navigation"><button className="is-selected" onClick={() => document.querySelector('textarea[aria-label="Message Lyra"]')?.focus()}><MessageSquare size={17} />Workspace<span className="nav-current" /></button><button onClick={onDesktop}><Terminal size={17} />Terminal workspace<ArrowUpRight size={13} className="nav-arrow" /></button><button onClick={onTasks}><PanelRight size={17} />Tasks & reminders</button></nav>
    <div className="sidebar-section-heading">YOUR CONVERSATIONS<span>{chats.length.toString().padStart(2, '0')}</span></div>
    <label className="conversation-search"><Search size={14} /><input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={event => setSearch(event.target.value)} /><kbd>⌕</kbd></label>
    <div className="conversation-list">{visible.length ? visible.map(chat => <div key={chat.id} className={`conversation-link ${activeChatId === chat.id ? 'is-active' : ''}`}><button onClick={() => onSelectChat(chat.id)}><MessageSquare size={13} /><span>{chat.title || 'Untitled conversation'}</span></button><button className="delete-conversation" aria-label={`Delete ${chat.title || 'conversation'}`} onClick={() => onDeleteChat(chat.id)}><Trash2 size={12} /></button></div>) : <div className="sidebar-empty"><span className="empty-line" /><p>{search ? 'No matching conversations.' : 'A little space for your next big idea.'}</p></div>}</div>
    <div className="sidebar-bottom"><label className="mode-select"><span>WORK MODE</span><div><select aria-label="Work mode" value={activeMode} onChange={event => setActiveMode(event.target.value)}>{MODES.map(mode => <option value={mode.id} key={mode.id}>{mode.label}</option>)}</select><ChevronDown size={13} /></div></label><div className="workspace-profile"><div className="profile-avatar">{user?.name?.[0] || 'L'}</div><div><strong>{user?.name || 'Your workspace'}</strong><span>Personal workspace</span></div><span className="profile-mark">↗</span></div></div>
  </aside>;
}
