import { http } from '@kit.NetworkKit';

export interface Account { username: string; role: string }
export interface Parcel {
  id: number;
  code: string;
  shelf: string;
  level: string;
  suffix: string;
  username?: string;
}
export interface StationNode { id: string; x: number; y: number; type: string }
export interface StationEdge { from: string; to: string }
export interface Layout { nodes: StationNode[]; directed_edges: StationEdge[] }
export interface Hours { weekday: string[]; weekend: string[] }
export interface Station { entry_node: string; operating_hours: Hours }
export interface StationInfo {
  station: Station;
  layout: Layout;
  today: string;
  tomorrow: string;
  current_time: string;
}
export interface Route {
  stops: string[];
  path: string[];
  distance_m: number;
  unreachable_shelves: string[];
}
export interface Arrival {
  time: string;
  wait_minutes: number;
  usual_low_minutes: number;
  usual_high_minutes: number;
  total_minutes: number | null;
  may_finish_after_close: boolean;
}
export interface Forecast { candidates: Arrival[]; message: string | null }
interface ErrorResponse { detail?: string }

export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

export class PickupApi {
  private base: string;
  private session: string = '';

  constructor(address: string) {
    this.base = address.trim().replace(/\/+$/, '');
    if (!/^https?:\/\/(?:[a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]+)?$/.test(this.base)) {
      throw new Error('请输入服务器地址，例如 https://pickup.example.com');
    }
  }

  async call<T>(path: string, body?: string, method?: http.RequestMethod): Promise<T> {
    const request = http.createHttp();
    const headers: Record<string, string> = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json; charset=utf-8';
    if (this.session) headers['Cookie'] = this.session;
    const options: http.HttpRequestOptions = {
      method: method ?? (body === undefined ? http.RequestMethod.GET : http.RequestMethod.POST),
      header: headers,
      expectDataType: http.HttpDataType.STRING,
      usingCache: false,
      connectTimeout: 8000,
      readTimeout: 10000
    };
    if (body !== undefined) options.extraData = body;
    try {
      const response = await request.request(this.base + path, options);
      const raw = response.result as string;
      if (response.responseCode < 200 || response.responseCode >= 300) {
        let detail = '请求失败（HTTP ' + response.responseCode + '）';
        try {
          const error = JSON.parse(raw) as ErrorResponse;
          if (typeof error.detail === 'string') detail = error.detail;
        } catch (_) {
          // Proxies can return an HTML response.
        }
        throw new ApiError(response.responseCode, detail);
      }
      const cookies = response.cookies ?? '';
      const match = /(?:^|[\s,;])(pickup_session=[a-zA-Z0-9_-]*)(?=[;\s,]|$)/.exec(cookies);
      if (match) this.session = match[1].endsWith('=') ? '' : match[1];
      return JSON.parse(raw) as T;
    } finally {
      request.destroy();
    }
  }
}
