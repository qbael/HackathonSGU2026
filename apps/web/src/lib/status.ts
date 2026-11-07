export type SystemStatus = {
  name: 'Findie API';
  stage: 'scaffold';
  database: 'ready' | 'unavailable';
  ai: 'ready' | 'unavailable';
  features: { business: boolean; authentication: boolean; storage: boolean };
};

export function readSystemStatus(value: unknown): SystemStatus {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Phản hồi trạng thái không hợp lệ.');
  }

  const status = value as Partial<SystemStatus>;
  if (
    status.name !== 'Findie API' ||
    status.stage !== 'scaffold' ||
    !['ready', 'unavailable'].includes(status.database ?? '') ||
    !['ready', 'unavailable'].includes(status.ai ?? '') ||
    typeof status.features?.business !== 'boolean' ||
    typeof status.features?.authentication !== 'boolean' ||
    typeof status.features?.storage !== 'boolean'
  ) {
    throw new Error('Phản hồi trạng thái không đúng hợp đồng khởi tạo.');
  }

  return status as SystemStatus;
}
