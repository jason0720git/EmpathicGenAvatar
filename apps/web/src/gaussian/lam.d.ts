declare module 'gaussian-splat-renderer-for-lam' {
  export const GaussianSplatRenderer: {
    getInstance(container: HTMLElement, assetPath: string, options: {
      getChatState: () => string; getExpressionData: () => Record<string, number>;
      backgroundColor: string; alpha: number; loadProgress?: (value: number) => void;
    }): Promise<unknown>
  }
}
