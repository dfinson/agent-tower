import { useShallow } from "zustand/react/shallow";
import { useStore, selectSignoffJobs, selectActiveJobs, selectAttentionJobs } from "../store";
import { KanbanColumn } from "./KanbanColumn";

export function KanbanBoard() {
  const activeJobs = useStore(useShallow(selectActiveJobs));
  const signoffJobs = useStore(useShallow(selectSignoffJobs));
  const attentionJobs = useStore(useShallow(selectAttentionJobs));

  return (
    <div className="grid grid-cols-3 gap-3 h-[calc(100vh-140px)] max-lg:grid-cols-2 max-sm:hidden">
      <KanbanColumn title="In Progress" jobs={activeJobs} />
      <KanbanColumn title="Needs Review" jobs={signoffJobs} />
      <KanbanColumn title="Needs Attention" jobs={attentionJobs} />
    </div>
  );
}
