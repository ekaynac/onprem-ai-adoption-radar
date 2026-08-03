import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import { TopBar } from "./TopBar";


function LocationProbe() {
  const location = useLocation();
  return <output aria-label="location">{location.pathname}{location.search}</output>;
}


test("global search navigates to the catalog query", async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/overview"]}>
      <TopBar staticMode />
      <LocationProbe />
    </MemoryRouter>,
  );

  await user.type(screen.getByRole("searchbox", { name: "Search intelligence" }), "Kimi K3{enter}");

  expect(screen.getByLabelText("location")).toHaveTextContent("/catalog?q=Kimi+K3");
});
