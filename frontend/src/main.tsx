import "./zod-config";
import "@fontsource-variable/bodoni-moda";
import "@fontsource-variable/martian-mono";
import "@fontsource-variable/schibsted-grotesk";
import "./styles/tokens.css";
import "./styles/globals.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { Providers } from "./app/providers";
import { createRouter } from "./app/router";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");

createRoot(root).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={createRouter()} />
    </Providers>
  </StrictMode>,
);
