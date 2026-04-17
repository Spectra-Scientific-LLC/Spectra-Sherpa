declare module "markdown-it-texmath" {
  type TexMathOptions = Record<string, unknown>;

  const texmath: (md: unknown, options?: TexMathOptions) => void;

  export default texmath;
}
