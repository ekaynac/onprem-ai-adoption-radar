import { PulsePage } from "../features/pulse/PulsePage";
import { AppShell } from "./shell/AppShell";


export function App() {
  return (
    <AppShell>
      <PulsePage />
    </AppShell>
  );
}
