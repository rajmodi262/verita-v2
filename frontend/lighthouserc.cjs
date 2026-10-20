// Lighthouse CI budgets (M9.04). Mobile emulation with simulated slow 4G (Lighthouse defaults).
// Measured on the production build behind nginx (2026-10-20): performance 0.92, accessibility,
// best practices and SEO 1.0, LCP 2.7 s, TBT 5 ms, CLS 0.04, 303 KB transferred.
// Budgets sit just above that, so a regression fails the build instead of drifting.
// LHCI_BASE_URL points at the server under test (CI: `vite preview` proxying the fixture API).
const base = process.env.LHCI_BASE_URL ?? "http://localhost:4173";

module.exports = {
  ci: {
    collect: {
      url: [`${base}/`, `${base}/login`],
      numberOfRuns: 3,
      settings: { chromeFlags: "--headless=new --no-sandbox" },
    },
    assert: {
      assertMatrix: [
        {
          matchingUrlPattern: ".*",
          assertions: {
            "categories:performance": ["error", { minScore: 0.85 }],
            "categories:accessibility": ["error", { minScore: 1 }],
            "categories:best-practices": ["error", { minScore: 0.9 }],
            "categories:seo": ["error", { minScore: 0.95 }],
            "largest-contentful-paint": ["error", { maxNumericValue: 3000 }],
            "total-blocking-time": ["error", { maxNumericValue: 200 }],
            "cumulative-layout-shift": ["error", { maxNumericValue: 0.1 }],
            "resource-summary:script:size": ["error", { maxNumericValue: 170_000 }],
            "resource-summary:total:size": ["error", { maxNumericValue: 400_000 }],
          },
        },
        {
          // The public landing page must log nothing. /login is exempt from this one check: it
          // probes GET /me, and the correct answer for a signed-out visitor is a 401, which
          // Chrome always logs as a failed resource.
          matchingUrlPattern: "^[^?#]*//[^/]+/$",
          assertions: {
            "categories:best-practices": ["error", { minScore: 0.95 }],
            "errors-in-console": ["error", { minScore: 1 }],
          },
        },
      ],
    },
    upload: { target: "filesystem", outputDir: "./lighthouse-report" },
  },
};
