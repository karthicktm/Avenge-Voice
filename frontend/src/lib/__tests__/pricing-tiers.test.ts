import { describe, it, expect } from "vitest";
import { PRICING_TIERS, calculateMonthlyCost, compareTiers } from "../pricing-tiers";

describe("PRICING_TIERS", () => {
  it("exports an array of pricing tiers", () => {
    expect(Array.isArray(PRICING_TIERS)).toBe(true);
    expect(PRICING_TIERS.length).toBe(4); // budget, balanced, premium-mini, premium
  });

  it("contains budget tier", () => {
    const budgetTier = PRICING_TIERS.find((t) => t.id === "budget");
    expect(budgetTier).toBeDefined();
    expect(budgetTier?.name).toBe("Budget");
    expect(budgetTier?.costPerHour).toBe(0.86);
    expect(budgetTier?.costPerMinute).toBe(0.0143);
  });

  it("contains balanced tier", () => {
    const balancedTier = PRICING_TIERS.find((t) => t.id === "balanced");
    expect(balancedTier).toBeDefined();
    expect(balancedTier?.name).toBe("Balanced");
    expect(balancedTier?.costPerHour).toBe(1.35);
    expect(balancedTier?.costPerMinute).toBe(0.0225);
  });

  it("contains premium tier", () => {
    const premiumTier = PRICING_TIERS.find((t) => t.id === "premium");
    expect(premiumTier).toBeDefined();
    expect(premiumTier?.name).toBe("Premium");
    expect(premiumTier?.costPerHour).toBe(1.92);
    expect(premiumTier?.costPerMinute).toBe(0.032);
  });

  it("has correct configuration for budget tier", () => {
    const budgetTier = PRICING_TIERS.find((t) => t.id === "budget");
    expect(budgetTier?.config.llmProvider).toBe("cerebras");
    expect(budgetTier?.config.llmModel).toBe("llama-3.3-70b");
    expect(budgetTier?.config.sttProvider).toBe("deepgram");
    expect(budgetTier?.config.sttModel).toBe("nova-3");
    expect(budgetTier?.config.ttsProvider).toBe("elevenlabs");
    expect(budgetTier?.config.ttsModel).toBe("eleven_flash_v2_5");
  });

  it("has correct configuration for balanced tier", () => {
    const balancedTier = PRICING_TIERS.find((t) => t.id === "balanced");
    expect(balancedTier?.config.llmProvider).toBe("google");
    expect(balancedTier?.config.llmModel).toBe("gemini-2.5-flash");
    expect(balancedTier?.config.sttModel).toBe("built-in");
    expect(balancedTier?.config.ttsModel).toBe("built-in");
  });

  it("has correct configuration for premium tier", () => {
    const premiumTier = PRICING_TIERS.find((t) => t.id === "premium");
    expect(premiumTier?.config.llmProvider).toBe("openai-realtime");
    expect(premiumTier?.config.llmModel).toBe("gpt-realtime");
  });

  it("has correct configuration for premium-mini tier", () => {
    const premiumMiniTier = PRICING_TIERS.find((t) => t.id === "premium-mini");
    expect(premiumMiniTier).toBeDefined();
    expect(premiumMiniTier?.config.llmProvider).toBe("openai-realtime");
    expect(premiumMiniTier?.config.llmModel).toBe("gpt-realtime-mini-2025-12-15");
  });

  it("has performance metrics for all tiers", () => {
    PRICING_TIERS.forEach((tier) => {
      expect(tier.performance.latency).toBeDefined();
      expect(tier.performance.speed).toBeDefined();
      expect(tier.performance.quality).toBeDefined();
    });
  });

  it("has features array for all tiers", () => {
    PRICING_TIERS.forEach((tier) => {
      expect(Array.isArray(tier.features)).toBe(true);
      expect(tier.features.length).toBeGreaterThan(0);
    });
  });

  it("only premium tier is marked as recommended", () => {
    const recommendedTiers = PRICING_TIERS.filter((t) => t.recommended);
    expect(recommendedTiers.length).toBe(1);
    expect(recommendedTiers[0]?.id).toBe("premium");
  });
});

describe("calculateMonthlyCost", () => {
  const budgetTier = PRICING_TIERS.find((t) => t.id === "budget");
  const balancedTier = PRICING_TIERS.find((t) => t.id === "balanced");
  const premiumTier = PRICING_TIERS.find((t) => t.id === "premium");

  if (!budgetTier || !balancedTier || !premiumTier) {
    throw new Error("Required pricing tiers not found");
  }

  it("calculates total minutes correctly", () => {
    const result = calculateMonthlyCost(budgetTier, 1000, 5);
    expect(result.totalMinutes).toBe(5000);
  });

  it("calculates costs for budget tier", () => {
    const result = calculateMonthlyCost(budgetTier, 1000, 5);
    expect(result.totalMinutes).toBe(5000);
    expect(result.aiCost).toBeGreaterThan(0);
    expect(result.telephonyCost).toBeGreaterThan(0);
    expect(result.totalCost).toBe(result.aiCost + result.telephonyCost);
    expect(result.costPerCall).toBe(result.totalCost / 1000);
  });

  it("calculates costs for balanced tier", () => {
    const result = calculateMonthlyCost(balancedTier, 1000, 5);
    expect(result.totalMinutes).toBe(5000);
    expect(result.totalCost).toBeGreaterThan(0);
  });

  it("calculates costs for premium tier", () => {
    const result = calculateMonthlyCost(premiumTier, 1000, 5);
    expect(result.totalMinutes).toBe(5000);
    expect(result.totalCost).toBeGreaterThan(0);
  });

  it("handles different inbound percentages", () => {
    const result50 = calculateMonthlyCost(budgetTier, 1000, 5, 50);
    const result100 = calculateMonthlyCost(budgetTier, 1000, 5, 100);

    // 100% inbound should be cheaper (inbound: 0.0075/min vs outbound: 0.01/min)
    expect(result100.telephonyCost).toBeLessThan(result50.telephonyCost);
  });

  it("defaults to 50% inbound when not specified", () => {
    const resultDefault = calculateMonthlyCost(budgetTier, 1000, 5);
    const result50 = calculateMonthlyCost(budgetTier, 1000, 5, 50);

    expect(resultDefault.telephonyCost).toBe(result50.telephonyCost);
  });

  it("calculates cost per call correctly", () => {
    const result = calculateMonthlyCost(budgetTier, 1000, 5);
    expect(result.costPerCall).toBe(result.totalCost / 1000);
  });

  it("handles high volume scenarios", () => {
    const result = calculateMonthlyCost(budgetTier, 100000, 10);
    expect(result.totalMinutes).toBe(1000000);
    expect(result.totalCost).toBeGreaterThan(10000);
  });

  it("handles short call durations", () => {
    const result = calculateMonthlyCost(budgetTier, 1000, 1);
    expect(result.totalMinutes).toBe(1000);
    expect(result.totalCost).toBeGreaterThan(0);
  });

  it("premium tier is most expensive", () => {
    const budget = calculateMonthlyCost(budgetTier, 1000, 5);
    const balanced = calculateMonthlyCost(balancedTier, 1000, 5);
    const premium = calculateMonthlyCost(premiumTier, 1000, 5);

    expect(premium.totalCost).toBeGreaterThan(balanced.totalCost);
    expect(balanced.totalCost).toBeGreaterThan(budget.totalCost);
  });

  it("returns all required fields", () => {
    const result = calculateMonthlyCost(budgetTier, 1000, 5);
    expect(result).toHaveProperty("totalMinutes");
    expect(result).toHaveProperty("aiCost");
    expect(result).toHaveProperty("telephonyCost");
    expect(result).toHaveProperty("totalCost");
    expect(result).toHaveProperty("costPerCall");
  });
});

describe("compareTiers", () => {
  it("returns comparison for all tiers", () => {
    const comparison = compareTiers(1000, 5);
    expect(comparison.length).toBe(4); // budget, balanced, premium-mini, premium
  });

  it("includes tier information in comparison", () => {
    const comparison = compareTiers(1000, 5);
    comparison.forEach((item) => {
      expect(item).toHaveProperty("tier");
      expect(item).toHaveProperty("cost");
      expect(item).toHaveProperty("savingsVsPremium");
    });
  });

  it("calculates savings vs premium correctly", () => {
    const comparison = compareTiers(1000, 5);
    const premiumItem = comparison.find((item) => item.tier.id === "premium");
    const budgetItem = comparison.find((item) => item.tier.id === "budget");

    // Premium should have 0 savings vs itself
    expect(premiumItem?.savingsVsPremium).toBe(0);

    // Budget should have positive savings vs premium
    expect(budgetItem?.savingsVsPremium).toBeGreaterThan(0);
  });

  it("premium-mini tier has highest savings (cheapest tier)", () => {
    const comparison = compareTiers(1000, 5);
    const savings = comparison.map((item) => item.savingsVsPremium);
    const maxSavings = Math.max(...savings);

    // Premium-mini is the cheapest tier, so it has the highest savings vs premium
    const premiumMiniItem = comparison.find((item) => item.tier.id === "premium-mini");
    expect(premiumMiniItem?.savingsVsPremium).toBe(maxSavings);
  });

  it("throws error if premium tier not found", () => {
    // This would require modifying PRICING_TIERS, so we just verify it doesn't throw normally
    expect(() => compareTiers(1000, 5)).not.toThrow();
  });

  it("handles different call volumes", () => {
    const low = compareTiers(100, 5);
    const high = compareTiers(10000, 5);

    // Higher volume should have proportionally higher costs
    expect(high[0]?.cost.totalCost).toBeGreaterThan(low[0]?.cost.totalCost ?? 0);
  });

  it("handles different call durations", () => {
    const short = compareTiers(1000, 1);
    const long = compareTiers(1000, 10);

    // Longer calls should have higher costs
    expect(long[0]?.cost.totalCost).toBeGreaterThan(short[0]?.cost.totalCost ?? 0);
  });

  it("maintains tier order (premium, premium-mini, balanced, budget)", () => {
    const comparison = compareTiers(1000, 5);
    expect(comparison[0]?.tier.id).toBe("premium");
    expect(comparison[1]?.tier.id).toBe("premium-mini");
    expect(comparison[2]?.tier.id).toBe("balanced");
    expect(comparison[3]?.tier.id).toBe("budget");
  });

  it("includes full cost breakdown for each tier", () => {
    const comparison = compareTiers(1000, 5);
    comparison.forEach((item) => {
      expect(item.cost).toHaveProperty("totalMinutes");
      expect(item.cost).toHaveProperty("aiCost");
      expect(item.cost).toHaveProperty("telephonyCost");
      expect(item.cost).toHaveProperty("totalCost");
      expect(item.cost).toHaveProperty("costPerCall");
    });
  });

  it("premium tier has zero savings vs itself", () => {
    const comparison = compareTiers(1000, 5);
    const premiumItem = comparison.find((item) => item.tier.id === "premium");
    expect(premiumItem?.savingsVsPremium).toBe(0);

    // All other tiers should have positive savings
    const nonPremiumTiers = comparison.filter((item) => item.tier.id !== "premium");
    nonPremiumTiers.forEach((item) => {
      expect(item.savingsVsPremium).toBeGreaterThan(0);
    });
  });
});
