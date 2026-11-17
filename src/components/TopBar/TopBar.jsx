import React, { useState } from 'react';
import { PanelLeft, SlidersHorizontal, ChevronDown, PanelRight, ArrowUpRight } from 'lucide-react';
import { MODES } from '../../utils/constants';
import { ModelRouter } from '../../modules/ModelRouter';
import ModelSelector from '../ModelSelector/ModelSelector';

export default function TopBar({ setSidebarOpen, activeMode, activePanel, setActivePanel, selectedModel, setSelectedModel, onDesktopMode, modeColor, onTasks }) {
  const [modelsOpen, setModelsOpen] = useState(false);
  const info = ModelRouter.getDisplayInfo(activeMode, selectedModel);
  const mode = MODES.find(item => item.id === activeMode);
  return <header className="workspace-header"><div className="workspace-breadcrumb"><button className="icon-button" aria-label="Toggle sidebar" onClick={() => setSidebarOpen(value => !value)}><PanelLeft size={18} /></button><span className="breadcrumb-divider">/</span><span>Workspace</span><span className="breadcrumb-divider">/</span><strong>{mode?.label || 'Assistant'}</strong></div><div className="header-actions"><div className="model-control"><button className="model-button" onClick={() => setModelsOpen(value => !value)} aria-expanded={modelsOpen}><span className="model-spark">✧</span>{selectedModel ? info.modelLabel : 'Auto model'}<ChevronDown size={12} /></button><ModelSelector isOpen={modelsOpen} onClose={() => setModelsOpen(false)} selectedModel={selectedModel} onSelectModel={setSelectedModel} activeMode={activeMode} modeColor={modeColor} /></div><button className={`icon-button ${activePanel === 'settings' ? 'is-active' : ''}`} aria-label="Settings" onClick={() => setActivePanel(value => value === 'settings' ? null : 'settings')}><SlidersHorizontal size={17} /></button><button className="icon-button" aria-label="Toggle tasks and reminders" onClick={onTasks}><PanelRight size={18} /></button><button className="computer-button" onClick={onDesktopMode}>Terminal<ArrowUpRight size={14} /></button></div></header>;
}
