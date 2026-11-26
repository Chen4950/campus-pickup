import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { http } from '@kit.NetworkKit';
import { scanBarcode } from '@kit.ScanKit';
import { preferences } from '@kit.ArkData';
import { Account, ApiError, Arrival, Forecast, Parcel, PickupApi, Route, StationInfo, StationNode } from '../PickupApi';

interface Credentials { username: string; password: string }
interface PasswordChange { current_password: string; new_password: string }
interface RouteQuery { start: string; excluded_ids: number[] }
interface ForecastQuery { day: string; earliest: string; latest: string; excluded_ids: number[] }
interface ScanQuery { code: string }

@Entry
@Component
struct Index {
  @State account: Account | null = null;
  @State station: StationInfo | null = null;
  @State parcels: Parcel[] = [];
  @State route: Route | null = null;
  @State forecast: Forecast | null = null;
  @State scanned: Parcel | null = null;
  @State server: string = '';
  @State username: string = '';
  @State password: string = '';
  @State currentPassword: string = '';
  @State newPassword: string = '';
  @State code: string = '';
  @State location: string = '';
  @State day: string = '';
  @State earliest: string = '10:00';
  @State latest: string = '20:00';
  @State registering: boolean = false;
  @State changing: boolean = false;
  @State busy: boolean = false;
  @State message: string = '';
  @State page: string = 'route';
  @State found: number[] = [];
  @State deferred: number[] = [];
  private api: PickupApi | null = null;
  private settings: preferences.Preferences | null = null;
  private map: CanvasRenderingContext2D = new CanvasRenderingContext2D(new RenderingContextSettings(true));

  aboutToAppear(): void {
    this.restoreAddress();
  }

  private async restoreAddress(): Promise<void> {
    try {
      this.settings = await preferences.getPreferences(getContext(this) as common.UIAbilityContext, 'pickup');
      const address = await this.settings.get('server', '');
      if (!this.server && typeof address === 'string') this.server = address;
    } catch (_) {
      // The server address can also be entered manually.
    }
  }

  private async saveAddress(): Promise<void> {
    if (!this.settings) return;
    try {
      await this.settings.put('server', this.server);
      await this.settings.flush();
    } catch (_) {
      // Address persistence is optional.
    }
  }

  private async run(task: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.message = '';
    try {
      await task();
    } catch (failure) {
      const error = failure as Error;
      if (error instanceof ApiError && error.status === 401 && this.account) this.clearAccount();
      this.message = error.message || '请求失败，请检查连接。';
    } finally {
      this.busy = false;
    }
  }

  private clearAccount(): void {
    this.account = null;
    this.api = null;
    this.station = null;
    this.parcels = [];
    this.route = null;
    this.forecast = null;
    this.scanned = null;
    this.location = '';
    this.day = '';
    this.found = [];
    this.deferred = [];
    this.code = '';
    this.password = '';
    this.currentPassword = '';
    this.newPassword = '';
    this.registering = false;
    this.changing = false;
    this.page = 'route';
  }

  private async authenticate(): Promise<void> {
    await this.run(async () => {
      const client = new PickupApi(this.server);
      const action = this.registering ? 'register' : 'login';
      const credentials: Credentials = {
        username: this.username.trim(), password: this.password
      };
      const account = await client.call<Account>('/api/auth/' + action, JSON.stringify(credentials));
      this.api = client;
      this.account = account;
      this.password = '';
      await this.saveAddress();
      if (account.role === 'user') await this.loadRoute(client);
    });
  }

  private hoursFor(day: string, station: StationInfo): string[] {
    const weekday = new Date(day + 'T12:00:00+08:00').getUTCDay();
    return weekday === 6 || weekday === 0 ? station.station.operating_hours.weekend :
      station.station.operating_hours.weekday;
  }

  private async loadRoute(client: PickupApi): Promise<void> {
    const station = await client.call<StationInfo>('/api/station');
    const parcels = await client.call<Parcel[]>('/api/parcels/mine');
    const location = station.layout.nodes.some((node: StationNode) => node.id === this.location && node.type === 'shelf') ?
      this.location : station.station.entry_node;

    const found = this.found.filter((id: number) => parcels.some((parcel: Parcel) => parcel.id === id));
    const deferred = this.deferred.filter((id: number) => parcels.some((parcel: Parcel) => parcel.id === id));
    const query: RouteQuery = { start: location, excluded_ids: found.concat(deferred) };
    const route = parcels.length ? await client.call<Route>('/api/routes', JSON.stringify(query)) : null;
    this.station = station;
    this.parcels = parcels;
    this.location = location;
    this.found = found;
    this.deferred = deferred;
    this.route = route;
    if (!this.day) {
      this.day = station.current_time >= this.hoursFor(station.today, station)[1] ? station.tomorrow : station.today;
      const hours = this.hoursFor(this.day, station);
      this.earliest = hours[0];
      this.latest = hours[1];
    }
    this.paintMap();
  }

  private refresh(): void {
    const client = this.api;
    if (client) {
      this.run(async () => {
        await this.loadRoute(client);
      });
    }
  }

  private compare(): void {
    const client = this.api;
    if (client) {
      this.run(async () => {
        const query: ForecastQuery = {
          day: this.day.trim(), earliest: this.earliest.trim(), latest: this.latest.trim(),
          excluded_ids: this.found.concat(this.deferred)
        };
        this.forecast = await client.call<Forecast>('/api/forecasts', JSON.stringify(query));
      });
    }
  }

  private scan(): void {
    try {
      const context = getContext(this) as common.UIAbilityContext;
      scanBarcode.startScanForResult(context, (error: BusinessError, result: scanBarcode.ScanResult) => {
        if (error) {
          if (error.code !== 1000500002) this.message = '无法打开扫码，请检查相机或手动输入包裹码。';
          return;
        }
        this.lookup(result.originalValue);
      });
    } catch (_) {
      this.message = '无法打开扫码，请手动输入包裹码。';
    }
  }

  private lookup(value: string): void {
    const client = this.api;
    if (this.busy || !client || this.account?.role !== 'admin' || !value.trim()) return;
    this.code = value.trim();
    this.scanned = null;
    this.run(async () => {
      const query: ScanQuery = { code: this.code };
      this.scanned = await client.call<Parcel>('/api/admin/pickup/lookup', JSON.stringify(query));
    });
  }

  private finish(id: number, discard: boolean): void {
    const client = this.api;
    if (!client) return;
    this.run(async () => {
      if (discard) await client.call<Object>('/api/admin/parcels/' + id, undefined, http.RequestMethod.DELETE);
      else await client.call<Object>('/api/admin/pickup/' + id, '{}');
      this.scanned = null;
      this.code = '';
      this.message = discard ? '包裹已丢弃。' : '包裹已核验出库。';
    });
  }

  private logout(): void {
    const client = this.api;
    if (!client) return;
    this.run(async () => {
      await client.call<Object>('/api/auth/logout', '{}');
      this.clearAccount();
    });
  }

  private changePassword(): void {
    const client = this.api;
    if (!client) return;
    this.run(async () => {
      const change: PasswordChange = {
        current_password: this.currentPassword, new_password: this.newPassword
      };
      await client.call<Object>('/api/auth/password', JSON.stringify(change));
      this.currentPassword = '';
      this.newPassword = '';
      this.changing = false;
      this.message = '密码已修改。';
    });
  }

  private paintMap(): void {
    const station = this.station;
    const w = this.map.width;
    const h = this.map.height;
    if (!station || w < 64 || h < 64 || station.layout.nodes.length === 0) return;
    const nodes = station.layout.nodes;
    const xs = nodes.map((node: StationNode) => node.x);
    const ys = nodes.map((node: StationNode) => node.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const spanX = Math.max(1, Math.max(...xs) - minX);
    const spanY = Math.max(1, Math.max(...ys) - minY);
    const x = (node: StationNode): number => 28 + (node.x - minX) / spanX * (w - 56);
    const y = (node: StationNode): number => h - 24 - (node.y - minY) / spanY * (h - 56);
    const points: Map<string, StationNode> = new Map();
    nodes.forEach((node: StationNode) => { points.set(node.id, node); });
    const drawLine = (from: string, to: string): void => {
      const a = points.get(from);
      const b = points.get(to);
      if (!a || !b) return;
      this.map.beginPath();
      this.map.moveTo(x(a), y(a));
      this.map.lineTo(x(b), y(b));
      this.map.stroke();
    };
    this.map.fillStyle = '#FFFFFF';
    this.map.fillRect(0, 0, w, h);
    this.map.lineWidth = 5;
    this.map.strokeStyle = '#C7D9D3';
    for (const edge of station.layout.directed_edges) drawLine(edge.from, edge.to);
    this.map.strokeStyle = '#16775E';
    const path = this.route?.path ?? [];
    for (let i = 1; i < path.length; i++) drawLine(path[i - 1], path[i]);
    this.map.fillStyle = '#0F5345';
    this.map.font = '12px sans-serif';
    this.map.textAlign = 'center';
    for (const node of nodes) {
      this.map.beginPath();
      this.map.arc(x(node), y(node), node.id === this.location ? 7 : 4, 0, 2 * Math.PI);
      this.map.fill();
      if (node.type !== 'aisle') this.map.fillText(node.id, x(node), y(node) - 10);
    }
  }

  private orderedParcels(): Parcel[] {
    const order = this.route?.stops ?? [];
    return this.parcels.slice().sort((first: Parcel, second: Parcel) => {
      const a = order.indexOf(first.shelf);
      const b = order.indexOf(second.shelf);
      return (a < 0 ? order.length : a) - (b < 0 ? order.length : b);
    });
  }

  private markParcel(parcel: Parcel, status: string): void {
    this.found = this.found.filter((id: number) => id !== parcel.id);
    this.deferred = this.deferred.filter((id: number) => id !== parcel.id);
    if (status === 'found') this.found = this.found.concat([parcel.id]);
    if (status === 'deferred') this.deferred = this.deferred.concat([parcel.id]);
    this.location = parcel.shelf;
    this.forecast = null;
    this.refresh();
  }

  @Builder
  loginForm() {
    Text(this.registering ? '注册普通账号' : '登录').fontSize(25).fontWeight(FontWeight.Bold);
    TextInput({ text: this.server, placeholder: '服务器地址，如 https://pickup.example.com' })
      .onChange((value: string) => { this.server = value; });
    TextInput({ text: this.username, placeholder: '用户名' })
      .onChange((value: string) => { this.username = value; });
    TextInput({ text: this.password, placeholder: this.registering ? '密码（至少 8 位）' : '密码' })
      .type(InputType.Password).onChange((value: string) => { this.password = value; });
    Button(this.registering ? '注册并登录' : '登录').width('100%').onClick(() => { this.authenticate(); });
    Button(this.registering ? '返回登录' : '注册新账号').type(ButtonType.Normal).onClick(() => {
      this.registering = !this.registering;
      this.password = '';
      this.message = '';
    });
  }

  @Builder
  routeView() {
    Text('站内取件路线').fontSize(24).fontWeight(FontWeight.Bold);
    Button('刷新包裹和路线').onClick(() => { this.refresh(); });
    if (this.station) {
      Select(this.station.layout.nodes
        .filter((node: StationNode) => node.type === 'shelf' || node.type === 'entrance')
        .map((node: StationNode): SelectOption => ({ value: node.id })))
        .value('当前位置 · ' + this.location)
        .onSelect((_index: number, value: string) => {
          this.location = value;
          this.refresh();
        });
      Canvas(this.map).width('100%').height(210)
        .onReady(() => { this.paintMap(); })
        .onAreaChange(() => { this.paintMap(); });
      if (!this.parcels.length) {
        Text('当前账号暂无待取包裹。');
      }
      if (this.route) {
        Text('建议顺序 · ' + this.route.stops.concat(['核验点', '出口']).join(' → '));
        Text('预计步行 ' + this.route.distance_m + ' 米');
        if (this.route.unreachable_shelves.length) {
          Text('暂时无法到达 ' + this.route.unreachable_shelves.join('、'));
        }
      }
      ForEach(this.orderedParcels(), (parcel: Parcel) => {
        Column({ space: 6 }) {
          Text(parcel.shelf + ' · 第 ' + parcel.level + ' 层 · 尾号 ' + parcel.suffix).fontWeight(FontWeight.Medium);
          Text(parcel.code);
          if (this.found.includes(parcel.id) || this.deferred.includes(parcel.id)) {
            Text(this.found.includes(parcel.id) ? '已找到' : '暂未找到');
            Button('重新查找').onClick(() => { this.markParcel(parcel, 'pending'); });
          } else {
            Row({ space: 8 }) {
              Button('已找到').onClick(() => { this.markParcel(parcel, 'found'); });
              Button('暂未找到').onClick(() => { this.markParcel(parcel, 'deferred'); });
            }
          }
        }.alignItems(HorizontalAlign.Start).width('100%').padding(10).backgroundColor(Color.White);
      }, (parcel: Parcel) => parcel.id.toString() + ':' + this.found.includes(parcel.id) + ':' +
        this.deferred.includes(parcel.id));
    }
  }

  @Builder
  forecastView() {
    Text('错峰计划').fontSize(24).fontWeight(FontWeight.Bold);
    Text('到站日期（年-月-日）');
    TextInput({ text: this.day, placeholder: 'YYYY-MM-DD' }).onChange((value: string) => {
      this.day = value;
      this.forecast = null;
    });
    Row({ space: 8 }) {
      Column({ space: 4 }) {
        Text('最早到站');
        TextInput({ text: this.earliest, placeholder: 'HH:mm' }).onChange((value: string) => {
          this.earliest = value;
          this.forecast = null;
        });
      }.layoutWeight(1);
      Column({ space: 4 }) {
        Text('最晚到站');
        TextInput({ text: this.latest, placeholder: 'HH:mm' }).onChange((value: string) => {
          this.latest = value;
          this.forecast = null;
        });
      }.layoutWeight(1);
    }.width('100%');
    Button('比较到站时段').onClick(() => { this.compare(); });
    if (this.forecast) {
      if (this.forecast.message) Text(this.forecast.message);
      ForEach(this.forecast.candidates, (slot: Arrival) => {
        Column({ space: 5 }) {
          Text(slot.time + ' · 预计排队 ' + slot.wait_minutes + ' 分钟').fontSize(18);
          Text('常见 ' + slot.usual_low_minutes + '–' + slot.usual_high_minutes + ' 分钟');
          if (slot.total_minutes !== null) Text('预计全程 ' + slot.total_minutes + ' 分钟');
          if (slot.may_finish_after_close) Text('预计离站时间可能晚于关门');
        }.alignItems(HorizontalAlign.Start).width('100%').padding(10).backgroundColor(Color.White);
      }, (slot: Arrival) => slot.time);
    }
  }

  @Builder
  scanView() {
    Text('扫码取件').fontSize(24).fontWeight(FontWeight.Bold);
    Button('打开相机扫码').onClick(() => { this.scan(); });
    TextInput({ text: this.code, placeholder: '包裹码' }).onChange((value: string) => {
      this.code = value;
      this.scanned = null;
    });
    Button('查找包裹').onClick(() => { this.lookup(this.code); });
    if (this.scanned) {
      Text(this.scanned.code).fontSize(20);
      Text((this.scanned.username ?? '') + ' · ' + this.scanned.shelf + ' 货架 · 尾号 ' + this.scanned.suffix);
      Row({ space: 8 }) {
        Button('确认取件').onClick(() => {
          if (this.scanned) this.finish(this.scanned.id, false);
        });
        Button('丢弃包裹').backgroundColor('#8C372D').onClick(() => {
          const parcel = this.scanned;
          if (!parcel) return;
          this.getUIContext().showAlertDialog({
            title: '确认丢弃该包裹？',
            message: parcel.code,
            primaryButton: { value: '取消', action: () => {} },
            secondaryButton: { value: '丢弃', action: () => { this.finish(parcel.id, true); } }
          });
        });
      }
    }
  }

  build() {
    Column() {
      Text('校园驿站').fontColor(Color.White).backgroundColor('#0F5345')
        .fontSize(24).fontWeight(FontWeight.Bold).width('100%').padding(16);
      Scroll() {
        Column({ space: 12 }) {
          if (this.busy) Text('正在处理…');
          if (this.message) Text(this.message).fontColor('#365E55');
          if (!this.account) {
            this.loginForm();
          } else {
            Text(this.account.username);
            Row({ space: 8 }) {
              Button('修改密码').onClick(() => { this.changing = !this.changing; });
              Button('退出登录').onClick(() => { this.logout(); });
            }
            if (this.changing) {
              TextInput({ text: this.currentPassword, placeholder: '当前密码' }).type(InputType.Password)
                .onChange((value: string) => { this.currentPassword = value; });
              TextInput({ text: this.newPassword, placeholder: '新密码（至少 8 位）' }).type(InputType.Password)
                .onChange((value: string) => { this.newPassword = value; });
              Button('保存新密码').onClick(() => { this.changePassword(); });
            }
            if (this.account.role === 'admin') {
              this.scanView();
            } else {
              Row({ space: 8 }) {
                Button('取件路线').onClick(() => { this.page = 'route'; this.refresh(); });
                Button('错峰计划').onClick(() => { this.page = 'forecast'; });
              }
              if (this.page === 'route') this.routeView();
              else this.forecastView();
            }
          }
        }.alignItems(HorizontalAlign.Start).width('100%').padding(16).enabled(!this.busy);
      }.layoutWeight(1).align(Alignment.Top);
    }.width('100%').height('100%').backgroundColor('#F2F7F5');
  }
}
