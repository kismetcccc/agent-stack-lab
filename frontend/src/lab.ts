export type LabPage<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
export type MysqlRecord = {
  id: string;
  name: string;
  value: string;
  created_at: string;
  updated_at: string;
};
export type MongoDocument = {
  id: string;
  document: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};
export type RedisSnapshot = {
  key: string;
  exists: boolean;
  value: string | null;
  ttl_ms: number;
  observed_at: string;
};
export type LabWrite = <T>(path: string, options: RequestInit) => Promise<T>;
export type LabProps = { write: LabWrite; onUnauthorized: () => void };
export const labTime = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { hour12: false });
export const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export type KafkaMessage = {
  id: string;
  topic: string;
  key: string;
  value: string;
  created_at: string;
  observed_at: string;
  producer: {
    status: "unconfirmed" | "acknowledged";
    acknowledged_at: string | null;
    partition: number | null;
    offset: number | null;
  };
  consumer: {
    status: "not_observed" | "received";
    received_at: string | null;
    group: string;
    partition: number | null;
    offset: number | null;
    key: string | null;
    value: string | null;
  };
};
