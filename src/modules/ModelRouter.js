/** Public provider/model metadata only. The backend chooses and authenticates inference. */
import { ModelRegistry } from './ModelRegistry';
export class ModelRouter {
  static getConfig(mode, overrideModelId = null) {
    const model = overrideModelId ? ModelRegistry.getModelById(overrideModelId) : null;
    return model ? { provider: model.provider, providerName: model.providerName, model: model.id, label: model.label, isVision: model.isVision, isCompound: model.isCompound, isOverride: true } : { provider: null, providerName: 'Backend', model: null, label: 'Backend-selected', isOverride: false };
  }
  static getDisplayInfo(mode, overrideModelId = null) {
    const config = this.getConfig(mode, overrideModelId);
    return { modelLabel: config.label, providerName: config.providerName, isNvidia: config.provider === 'nvidia', isGemini: config.provider === 'gemini', isOpenRouter: config.provider === 'openrouter', isVision: config.isVision, isCompound: config.isCompound, isOverride: config.isOverride };
  }
  static getAllModels() { return ModelRegistry.getAllModels(); }
  static getModelsGrouped() { return ModelRegistry.getModelsGrouped(); }
  static getModelById(id) { return ModelRegistry.getModelById(id); }
  static getProviders() { return ModelRegistry.getProviders(); }
}
export default ModelRouter;
