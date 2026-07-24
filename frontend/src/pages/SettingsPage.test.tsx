import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { DataSettings, TargetSettings } from "./SettingsPage";

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

describe("DataSettings selective restore", () => {
  it("previews an archive and restores only the checked domains", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "me").mockResolvedValue({
      id: "owner-1",
      username: "owner",
      role: "owner",
      member_id: "member-1",
      must_change_password: false,
      ingredient_locale: "uk",
    });
    vi.spyOn(api, "backupStatus").mockResolvedValue({ available: true, last_backup: "20260724-120000", tier: "daily" });
    vi.spyOn(api, "restoreArchives").mockResolvedValue({
      archives: [{
        archive: "daily/20260724-120000",
        tier: "daily",
        timestamp: "20260724-120000",
        manifest: {},
        files: { database_dump: true, data_archive: true, checksums: true },
        selective_restore_available: true,
      }],
    });
    vi.spyOn(api, "previewRestore").mockResolvedValue({
      archive: "daily/20260724-120000",
      tier: "daily",
      timestamp: "20260724-120000",
      manifest: {},
      files: { database_dump: true, data_archive: true, checksums: true },
      selective_restore_available: true,
      households: [{ id: "source-household", name: "Old home", timezone: "Europe/London" }],
      selected_household: { id: "source-household", name: "Old home", timezone: "Europe/London" },
      components: [
        { key: "recipes", label: "Recipes", description: "Saved recipes", counts: { recipes: 4 } },
        { key: "ingredients", label: "Ingredients & nutrition", description: "Saved foods", counts: { food_records: 7 } },
      ],
      excluded: [],
    });
    const restore = vi.spyOn(api, "restoreSelected").mockResolvedValue({
      archive: "daily/20260724-120000",
      source_household: "Old home",
      components: ["recipes", "ingredients"],
      imported: { recipe: 4, food_record: 7 },
      excluded: [],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <DataSettings />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByRole("option", { name: /20260724-120000/ })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Backup archive"), "daily/20260724-120000");
    await user.click(screen.getByRole("button", { name: "Inspect archive" }));
    expect(await screen.findByText("Old home")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Recipes/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Ingredients & nutrition/ })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Restore 2 selected" }));
    await waitFor(() => expect(restore).toHaveBeenCalledWith("daily/20260724-120000", ["recipes", "ingredients"], "source-household"));
    expect(await screen.findByText(/Imported 4 recipe/)).toBeInTheDocument();
  });
});
