import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { TargetSettings } from "./SettingsPage";

afterEach(() => vi.restoreAllMocks());

describe("TargetSettings", () => {
  it("saves calorie-mode macro minimums and defaults unconstrained macros to zero", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "listMembers").mockResolvedValue([
      { id: "member-1", name: "Alex", active: true, version: 1 },
    ]);
    vi.spyOn(api, "getTarget").mockResolvedValue({
      id: "target-1",
      member_id: "member-1",
      mode: "calorie",
      calorie_target: 2000,
      tolerance_percent: 5,
      allocations: [
        { meal_type: "breakfast", percentage: 25 },
        { meal_type: "lunch", percentage: 30 },
        { meal_type: "dinner", percentage: 35 },
        { meal_type: "snack", percentage: 10 },
      ],
      version: 1,
    });
    const setTarget = vi.spyOn(api, "setTarget").mockResolvedValue({});

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <TargetSettings />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const protein = await screen.findByRole("spinbutton", {
      name: /Minimum protein/,
    });
    expect(protein).toHaveValue(0);
    expect(screen.getByRole("spinbutton", { name: /Minimum fat/ })).toHaveValue(0);
    expect(
      screen.getByRole("spinbutton", { name: /Minimum carbohydrate/ }),
    ).toHaveValue(0);

    await user.clear(protein);
    await user.type(protein, "130");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(setTarget).toHaveBeenCalledOnce());
    expect(setTarget).toHaveBeenCalledWith(
      "member-1",
      expect.objectContaining({
        mode: "calorie",
        protein_min_g: 130,
        carbohydrate_min_g: 0,
        fat_min_g: 0,
      }),
    );
  });
});
