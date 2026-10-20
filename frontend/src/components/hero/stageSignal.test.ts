import { applyStageSignal, IDLE } from "./stageSignal";

it("writes the coin's facing and shows, then hides, the pattern caption", () => {
  const stage = document.createElement("header");
  const caption = document.createElement("p");

  applyStageSignal(stage, caption, { face: 0.5, caption: "Pattern detected · FAN-IN" });
  expect(stage.style.getPropertyValue("--face")).toBe("0.500");
  expect(caption.textContent).toBe("Pattern detected · FAN-IN");
  expect(caption.dataset.on).toBe("true");

  caption.dataset.on = "untouched";
  applyStageSignal(stage, caption, { face: 1, caption: "Pattern detected · FAN-IN" });
  expect(caption.dataset.on).toBe("untouched"); // same caption: no DOM write

  applyStageSignal(stage, caption, { face: 0, caption: null });
  expect(caption.textContent).toBe(IDLE);
  expect(caption.dataset.on).toBe("false");
});

it("tolerates the page not being mounted yet", () => {
  expect(() => {
    applyStageSignal(null, null, { face: 1, caption: null });
  }).not.toThrow();
});
