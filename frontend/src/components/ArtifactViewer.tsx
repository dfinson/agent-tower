import { useEffect, useState } from "react";
import { Paper, Table, Text, Badge, Anchor, Group, Loader } from "@mantine/core";
import { type LucideIcon, Download, FileText, FileCode } from "lucide-react";
import { fetchArtifacts, downloadArtifactUrl } from "../api/client";

interface Artifact {
  id: string;
  jobId: string;
  name: string;
  type: string;
  mimeType: string;
  sizeBytes: number;
  phase: string;
  createdAt: string;
}

const TYPE_ICON: Record<string, LucideIcon> = {
  diff_snapshot: FileCode,
  custom: FileText,
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props { jobId: string; }

export default function ArtifactViewer({ jobId }: Props) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchArtifacts(jobId)
      .then((res) => setArtifacts(res.items as Artifact[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [jobId]);

  if (loading) return <div className="flex justify-center py-10"><Loader /></div>;

  if (artifacts.length === 0) {
    return (
      <Paper radius="lg" p="xl">
        <Text size="sm" c="dimmed" ta="center">No artifacts available</Text>
      </Paper>
    );
  }

  return (
    <Paper radius="lg" p={0} className="overflow-hidden">
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Type</Table.Th>
            <Table.Th>Size</Table.Th>
            <Table.Th>Created</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {artifacts.map((a) => {
            const Icon = TYPE_ICON[a.type] ?? FileText;
            return (
              <Table.Tr key={a.id}>
                <Table.Td>
                  <Group gap="xs">
                    <Icon size={14} />
                    <Text size="sm">{a.name}</Text>
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" size="sm">{a.type}</Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{formatSize(a.sizeBytes)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{new Date(a.createdAt).toLocaleString()}</Text>
                </Table.Td>
                <Table.Td>
                  <Anchor href={downloadArtifactUrl(a.id)} target="_blank" size="sm">
                    <Download size={14} />
                  </Anchor>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}
