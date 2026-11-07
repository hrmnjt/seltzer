/** True in the design-preview build (`npm run build:demo`), which runs on a fake in-browser API. */
export const isDemo = import.meta.env.MODE === "demo";
