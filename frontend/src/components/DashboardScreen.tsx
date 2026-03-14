import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Group, Title, Button } from "@mantine/core";
import { Plus } from "lucide-react";
import { useTowerStore } from "../store";
import { fetchJobs } from "../api/client";
import { KanbanBoard } from "./KanbanBoard";
import { MobileJobList } from "./MobileJobList";

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
      <Group justify="space-between" mb="md">
        <Title order={3}>Jobs</Title>
        <Button
          leftSection={<Plus size={16} />}
          onClick={() => navigate("/jobs/new")}
        >
          New Job
        </Button>
      </Group>
      <KanbanBoard />
      <MobileJobList />
    </div>
  );
}
