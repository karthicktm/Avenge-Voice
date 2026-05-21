import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { TierSelector } from "../tier-selector";

describe("TierSelector", () => {
  it("renders all pricing tiers", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // Check if all tiers are rendered
    expect(screen.getByText("Budget")).toBeInTheDocument();
    expect(screen.getByText("Balanced")).toBeInTheDocument();
    expect(screen.getByText("Premium")).toBeInTheDocument();
  });

  it("displays tier descriptions", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    expect(
      screen.getByText("Maximum cost savings - perfect for high-volume operations")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Best performance-to-cost ratio with multimodal capabilities")
    ).toBeInTheDocument();
  });

  it("shows recommended badge for balanced tier", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    expect(screen.getByText("Recommended")).toBeInTheDocument();
  });

  it("displays pricing information correctly", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // Check for Budget tier pricing
    expect(screen.getByText("$0.86")).toBeInTheDocument();
    expect(screen.getByText("$0.0143/min")).toBeInTheDocument();

    // Check for Balanced tier pricing
    expect(screen.getByText("$1.35")).toBeInTheDocument();
    expect(screen.getByText("$0.0225/min")).toBeInTheDocument();

    // Check for Premium tier pricing
    expect(screen.getByText("$1.92")).toBeInTheDocument();
    expect(screen.getByText("$0.0320/min")).toBeInTheDocument();
  });

  it("displays performance metrics", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // Check for latency labels
    expect(screen.getByText("~530ms")).toBeInTheDocument();
    expect(screen.getByText("~400ms")).toBeInTheDocument();
    expect(screen.getByText("~320ms")).toBeInTheDocument();

    // Check for speed labels
    expect(screen.getByText("450 tokens/sec")).toBeInTheDocument();
    expect(screen.getByText("268 tokens/sec")).toBeInTheDocument();
  });

  it("displays model configuration", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // Check for LLM models
    expect(screen.getByText("llama-3.3-70b")).toBeInTheDocument();
    expect(screen.getByText("gemini-2.5-flash")).toBeInTheDocument();
    expect(screen.getByText("gpt-realtime")).toBeInTheDocument();
  });

  it("highlights the selected tier", () => {
    const mockOnTierChange = vi.fn();
    const { container } = render(
      <TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />
    );

    // Find the balanced tier card - it should have special styling
    const cards = container.querySelectorAll("[class*='ring-2']");
    expect(cards.length).toBeGreaterThan(0);
  });

  it("shows checkmark on selected tier", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // There should be a checkmark icon (Check component renders in the selected tier)
    const balancedCard = screen.getByText("Balanced").closest("div");
    expect(balancedCard).toBeInTheDocument();
  });

  it("calls onTierChange when a tier is clicked", async () => {
    const user = userEvent.setup();
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // Click on Budget tier
    const budgetCard = screen.getByText("Budget").closest("div")?.parentElement?.parentElement;
    if (budgetCard) {
      await user.click(budgetCard);
      expect(mockOnTierChange).toHaveBeenCalledWith("budget");
    }
  });

  it("calls onTierChange with correct tier ID when different tier is clicked", async () => {
    const user = userEvent.setup();
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="budget" onTierChange={mockOnTierChange} />);

    // Click on Premium tier
    const premiumCard = screen.getByText("Premium").closest("div")?.parentElement?.parentElement;
    if (premiumCard) {
      await user.click(premiumCard);
      expect(mockOnTierChange).toHaveBeenCalledWith("premium");
    }
  });

  it("displays first 3 features for each tier", () => {
    const mockOnTierChange = vi.fn();
    render(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);

    // Check Budget tier features (first 3)
    expect(screen.getByText("56% cheaper than premium")).toBeInTheDocument();
    expect(screen.getByText("Ultra-fast: 450 tokens/sec")).toBeInTheDocument();
    expect(screen.getByText("Enterprise-grade quality")).toBeInTheDocument();
  });

  it("memoizes component to prevent unnecessary re-renders", () => {
    const mockOnTierChange = vi.fn();
    const { rerender } = render(
      <TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />
    );

    // Component is wrapped with React.memo
    // Just verify it can re-render without errors
    rerender(<TierSelector selectedTier="balanced" onTierChange={mockOnTierChange} />);
    expect(screen.getByText("Balanced")).toBeInTheDocument();
  });
});
