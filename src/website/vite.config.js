import { fileURLToPath } from "node:url";

export default {
  base: "./",
  build: {
    rollupOptions: {
      input: {
        markets: fileURLToPath(new URL("./index.html", import.meta.url)),
        games: fileURLToPath(new URL("./games/index.html", import.meta.url)),
      },
    },
  },
};
