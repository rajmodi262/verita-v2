import { render, screen } from "@testing-library/react";

import { ThemeProvider, useTheme } from "./theme";

function Probe() {
  const { theme } = useTheme();
  return <p>theme:{theme}</p>;
}

function stubColorScheme(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: dark })),
  );
}

it("opens on the night stage when nothing is stored, whatever the system says", () => {
  stubColorScheme(false);
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByText("theme:night")).toBeInTheDocument();
});

it("prefers the stored choice over the system", () => {
  stubColorScheme(true);
  localStorage.setItem("verita.theme", "paper");
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByText("theme:paper")).toBeInTheDocument();
});

it("ignores a corrupted stored value", () => {
  stubColorScheme(false);
  localStorage.setItem("verita.theme", "neon");
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByText("theme:night")).toBeInTheDocument();
});

it("keeps working when storage throws", () => {
  stubColorScheme(false);
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByText("theme:night")).toBeInTheDocument();
});

it("throws a clear error outside the provider", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  expect(() => render(<Probe />)).toThrow("useTheme must be used inside <ThemeProvider>");
});
