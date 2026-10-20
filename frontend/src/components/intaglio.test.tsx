import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";

import { subgraph } from "../test/alertFixtures";
import { frontier } from "../test/capacityFixtures";

import { EvidenceThreads } from "./case/EvidenceThreads";
import { FrontierChart } from "./charts/FrontierChart";
import { RiskTape } from "./charts/RiskTape";
import { TransitMap } from "./graph/TransitMap";
import { GuillocheSeal } from "./seal/GuillocheSeal";
import { TypologyGlyph } from "./TypologyGlyph";

const ROOT = "94ebaa1c818747ab2f1e0c3d5a5e9498aa11bb22cc33dd44ee55ff6677889900";

describe("GuillocheSeal", () => {
  it("is intact with one sector per leaf", () => {
    render(<GuillocheSeal root={ROOT} leaves={["a", "b", "c"]} serial="000007" />);
    expect(screen.getByRole("img", { name: /Seal intact: 3 exhibits/ })).toBeInTheDocument();
    expect(screen.getByText("SEALED")).toBeInTheDocument();
  });

  it("breaks the sector of a changed leaf and names it", () => {
    const { container } = render(
      <GuillocheSeal root={ROOT} leaves={["a", "b", "c"]} broken={["b"]} serial="000007" />,
    );
    expect(screen.getByRole("img", { name: /Seal broken: 1 of 3 .*\(b\)/ })).toBeInTheDocument();
    expect(screen.getByText("BROKEN")).toBeInTheDocument();
    expect(container.querySelectorAll("clipPath")).toHaveLength(1);
  });

  it("still draws from a root that is not hex", () => {
    render(<GuillocheSeal root="not-a-hash" leaves={[]} serial="1" />);
    expect(screen.getByRole("img", { name: /Seal intact/ })).toBeInTheDocument();
  });
});

describe("RiskTape", () => {
  const days = [
    { date: "2022-09-09", alerts: 900 },
    { date: "2022-09-08", alerts: 100 },
  ];

  it("summarises the days and filters on click, clearing on a second click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { rerender } = render(<RiskTape days={days} selected={undefined} onSelect={onSelect} />);
    expect(screen.getByText(/1,000 alerts over 2 days · busiest 2022-09-09/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "2022-09-08: 100 alerts" }));
    expect(onSelect).toHaveBeenLastCalledWith("2022-09-08");
    rerender(<RiskTape days={days} selected="2022-09-08" onSelect={onSelect} />);
    const on = screen.getByRole("button", { name: "2022-09-08: 100 alerts" });
    expect(on).toHaveAttribute("aria-pressed", "true");
    await user.click(on);
    expect(onSelect).toHaveBeenLastCalledWith(undefined);
  });

  it("renders nothing without days", () => {
    const { container } = render(<RiskTape days={[]} selected={undefined} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TypologyGlyph", () => {
  it("draws known shapes and a dashed ring for anything else", () => {
    const { container } = render(
      <>
        <TypologyGlyph typology="FAN-IN" />
        <TypologyGlyph typology="UNATTRIBUTED" />
      </>,
    );
    expect(container.querySelectorAll("path")).toHaveLength(1);
    expect(container.querySelectorAll("circle")).toHaveLength(1);
  });
});

describe("TransitMap", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("replays the payments in order and calls out the riskiest", () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    render(<TransitMap graph={subgraph(7)} selectedTxn={null} onSelectTxn={onSelect} />);
    const map = screen.getByRole("img", { name: /2 payments, drawn as a transit map \(2 shown\)/ });
    expect(map.querySelectorAll("path[pathLength]")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByText(/press play/)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(4600);
    });
    expect(screen.getByText(/Alert fires/)).toBeInTheDocument(); // 1001 is the riskiest
    act(() => {
      vi.advanceTimersByTime(4600);
    });
    expect(screen.queryByText(/Alert fires/)).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.getByRole("button", { name: "Replay" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Payments shown"), { target: { value: "1" } });
    expect(map.querySelectorAll("path[pathLength]")).toHaveLength(1);
    fireEvent.click(map.querySelector("path[pathLength]")!);
    expect(onSelect).toHaveBeenCalledWith(1001);
  });
});

describe("FrontierChart", () => {
  it("staffs the day from a click on the chart", () => {
    const onChange = vi.fn();
    const points = frontier().points;
    const first = points[0]!;
    const { container } = render(
      <FrontierChart
        points={points}
        analysts={first.analysts}
        targetRecall={0.95}
        onAnalystsChange={onChange}
      />,
    );
    const svg = container.querySelector("svg")!;
    svg.getBoundingClientRect = () => ({ left: 0, width: 640 }) as DOMRect;
    const surface = [...svg.querySelectorAll("rect")].at(-1)!;
    fireEvent.pointerDown(surface, { clientX: 620 });
    expect(onChange).toHaveBeenCalledWith(points.at(-1)!.analysts);
    onChange.mockClear();
    fireEvent.pointerMove(surface, { clientX: 300, buttons: 0 });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("EvidenceThreads", () => {
  function Harness({ sentence }: { sentence: number | null }) {
    const ref = useRef<HTMLDivElement>(null);
    return (
      <div ref={ref}>
        <p data-sentence="0">S1</p>
        <button type="button" data-ev="EV-1">
          EV-1
        </button>
        <details>
          <summary>Payments</summary>
          <button type="button" data-ev="EV-2">
            EV-2
          </button>
        </details>
        <EvidenceThreads root={ref} sentence={sentence} ids={["EV-1", "EV-2", "EV-9"]} failed />
      </div>
    );
  }

  it("draws a thread to each cited exhibit that exists", async () => {
    // As in the app: the page renders first, then a sentence is read (hover or focus).
    const { container, rerender } = render(<Harness sentence={null} />);
    rerender(<Harness sentence={0} />);
    await act(async () => {
      await new Promise((r) => requestAnimationFrame(r));
    });
    expect(container.querySelectorAll("svg path")).toHaveLength(2);
    rerender(<Harness sentence={null} />);
    expect(container.querySelector("svg")).toBeNull();
  });
});
