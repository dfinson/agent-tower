import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTowerStore } from "../store";
import { fetchJobs } from "../api/client";
import { KanbanBoard } from "./KanbanBoard";
import { MobileJobList } from "./MobileJobList";
import { Button } from "../ui/Button";

export function DashboardScreen() {
  const navigate = useNavigate();

  useEffect(() => {
    fetchJobs({ limit: 100 })
      .then((result) => {
        useTowerStore.setState((state) => {
          const updated = { ...state.jobs };
          for (const job of result.items) updated[job.id] = job;
          return { jobs: updated };
        });
      })
      .catch(() => {});
  }, []);

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Jobs</h2>
        <Button variant="primary" onClick={() => navigate("/jobs/new")}>
          + New Job
        </Button>
      </div>
      <KanbanBoard />
      <MobileJobList />
    </div>
  );
}
