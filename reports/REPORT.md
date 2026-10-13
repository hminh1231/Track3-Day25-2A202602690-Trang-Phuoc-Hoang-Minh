# Lab 25B — Report

**Họ tên / nhóm:** Trang Phước Hoàng Minh — MSV 2A202602690  **Commit:** …  **Điểm tự động (`make grade`):** 84 / 88
(4 điểm còn lại là dữ liệu SLO ẩn do giảng viên chấm; `make grade --seeds 25,26,27` cũng cho 84/88, mọi băng PASS trên cả 3 seed)

> Số liệu lấy từ `reports/gameday/*.json`, `reports/workflows.json`, `reports/slo.json`, `reports/cache/*.json` (seed 25).
> Các thí nghiệm ở mục 3 và 8 chạy bằng `run_scenario` với cùng seed 25, chỉ đổi một vài tham số; số "baseline" của
> thí nghiệm có thể lệch nhẹ so với bảng mục 1 vì seed RNG của client khác nhau.

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0,7194 | 7,157 | 7,738 | 6,738 | 2,163 | 4 | ❌ availability, retry-after (36.027 vi phạm), amplification |
| G1 | yours | 1,0 | 4,725 | 1,064 | 0,002 | 2,099 | 0 | ✅ (0 vi phạm retry-after) |
| G2 | naive | 0,456 | 15,034 | 9,904 | 8,904 | 4,627 | 155 | ❌ availability, amplification, recovery |
| G2 | yours | 1,0 | 10,746 | 1,038 | 0,005 | 2,116 | 0 | ✅ (primary share sau hồi phục 1,0) |
| G3 | naive | 1,0 | 4,768 | 1,164 | 0,164 | 2,328 | 0 | ❌ retry_ratio |
| G3 | yours | 1,0 | 4,718 | 1,065 | 0,035 | 2,146 | 0 | ✅ |
| G4 | naive | 1,0 | 13,764 | 1,004 | 0,004 | 2,008 | 0 | ❌ p95 |
| G4 | yours | 1,0 | 5,684 | 1,013 | 0,002 | 2,069 | 0 | ✅ (primary share 1,0) |
| G5 | naive | 0,3699 | 5,359 | 17,03 | 16,03 | 2,124 | – | ❌ 9.149 retry trên lỗi 400, availability |
| G5 | yours | 0,8179 | 5,482 | 1,003 | 0,002 | 2,504 | – | ✅ (0 retry lỗi 400, 0 failover thừa) |
| G6 | naive | 0,517 | 4,836 | 12,344 | 11,344 | 2,009 | 0 | ❌ availability |
| G6 | yours | 0,9933 | 6,119 | 1,054 | 0,016 | 2,2 | 0 | ✅ (0 incompatible route) |

Ngoài seed 25, tôi kiểm tra độ bền bằng 9 biến thể của 6 băng: lệch thời điểm −40/0/+45 s và cường độ ×0,8/1,0/1,25.
Mỗi biến thể chạy 5 seed, tổng 270 lần chạy, 0 lần FAIL.

## 2. Cấu hình client và lý do

Bộ giá trị mặc định đã PASS cả 6 băng, kể cả 270 lần chạy nhiễu, nên tôi giữ nguyên. Lý do cho từng giá trị:

| Tham số | Giá trị | Vì sao (dựa trên băng nào, số liệu nào) |
|---|---:|---|
| attempt_timeout_s | 8 | ≈ 4–6× p50 lúc bình thường (alpha 1,2 s, beta 1,8 s). Vẫn còn ≥ 2 lần fail over trong deadline 30 s. G6 (alpha-eu treo): timeout 8 → avail 0,990; timeout 30 → 0,944 với 107 lượt chết vì `deadline` (TN 2) |
| max_attempts_per_provider | 2 | 1 retry cùng provider đủ cứu lỗi 500 lẻ tẻ ở G3 (retry_ratio 0,035 ≤ 0,10). Lỗi kéo dài thì fail over là tốt hơn. TN 1: tăng lên 5 khi breaker hỏng thì G2 amplification lên 1,38–1,68 |
| backoff_base_s / cap_s | 0,25 / 4 | Full jitter, retry thứ 1 chờ 0–0,25 s: đủ nhanh cho user nhưng tản các retry ra theo thời gian. Cap 4 s để không ăn hết deadline 30 s. Có `retry_after` thì chờ `retry_after + U(0, 0,25)`: G1 có 0 vi phạm |
| retry_budget_ratio | 0,1 | Retry ≤ ~10% lần gửi đầu, khớp ngưỡng retry_ratio ≤ 0,10 của G3. TN 1: khi breaker hỏng, budget giữ G2 retry_ratio 0,058 thay vì 0,499 |
| breaker.window_size / min_calls | 20 / 10 | Ở 4 lượt/s, alpha nhận ~8 call/s nên cửa sổ 20 kết quả ≈ 2–3 s gần nhất: trip nhanh ở G2/G6. min_calls 10 để 1–2 lỗi lẻ (G3 base error) không mở breaker |
| breaker.failure_rate_threshold | 0,5 | G3 có 30% lỗi 500: không trip, retry 1 lần là đủ (avail 1,0, primary vẫn gánh tải). G2/G6 có ≫ 50% lỗi/timeout: trip ngay |
| breaker.slow_call_s | 5 | Bình thường p95 của alpha ≈ 3–4 s. G4 thêm 5 s → mọi call > 6 s nên tỷ lệ chậm vượt 0,6 và breaker mở. Kết quả p95 13,76 s → 5,68 s |
| breaker.open_duration_s | 10 | Đủ ngắn để sau khi provider hồi phục traffic quay về alpha trong vài chục giây: G2 recovery 0 s, primary share 1,0; G4 primary share 1,0 |
| breaker.half_open_max_probes | 2 (cần 2 thành công) | Chỉ 2 request dò provider vừa hồi phục, không đổ cả hàng đợi vào alpha khi nó còn yếu. 2 thành công liên tiếp mới đóng, tránh đóng nhầm vì 1 call may mắn |

Sơ đồ quyết định của `on_error`:

```
lỗi ──► classify()
 ├─ CLIENT_ERROR (400/401/422) ─► breaker.release ─► GiveUp("client_error")   (không retry, không failover)
 ├─ QUOTA_EXHAUSTED (429 quota) ─► breaker.release ─► cooldown provider 300 s ─► failover ngay
 ├─ RATE_LIMITED (429 + retry-after) ─► breaker.release ─► cooldown = now + retry_after (dùng chung mọi call)
 │                                                     ─► failover ngay (spillover, delay 0)
 └─ OVERLOADED / SERVER_ERROR / TIMEOUT ─► breaker.on_failure
        ├─ tries < 2  AND breaker chưa OPEN AND còn kịp deadline AND retry budget còn token
        │       ─► retry CÙNG provider sau backoff.delay(tries)  (full jitter / tôn trọng retry-after)
        └─ ngược lại ─► failover sang provider kế tiếp trong ladder

_route: bỏ qua provider đang cooldown hoặc breaker OPEN / HALF_OPEN đã hết slot probe.
Hết ladder ─► chờ cooldown rate-limit ngắn nhất (≤ 5 s, breaker không OPEN, kịp deadline), tối đa 1 lần / call
            ─► nếu không có: GiveUp("no_provider_available")
ladder(task): call "tool" chỉ đi alpha → alpha-eu → beta (gamma-mini không có tool calling).
```

## 3. Ba thí nghiệm

**1. Retry budget là lớp phòng thủ cuối.** Breaker hỏng (`min_calls: 1e9`, không bao giờ trip) và `max_attempts_per_provider: 5`:

| Băng | Cấu hình | availability | amplification | retry_ratio | recovery (s) | p95 (s) |
|---|---|---:|---:|---:|---:|---:|
| G2 | cấu hình đúng | 1,0 | 1,055 | 0,007 | 0 | 11,9 |
| G2 | breaker hỏng, budget **bật** | 0,9987 | 1,382 | 0,058 | 0 | 19,3 |
| G2 | breaker hỏng, budget **tắt** | 0,9657 | **1,678** (> 1,6: FAIL) | **0,499** | 25 | 22,3 |
| G3 | breaker hỏng, budget bật | 1,0 | 1,135 | 0,067 | 0 | 4,6 |
| G3 | breaker hỏng, budget tắt | 1,0 | 1,163 | **0,162** (> 0,10: FAIL) | 0 | 4,8 |

Khi breaker không làm việc, budget là thứ duy nhất chặn retry storm. Ở G2, budget giữ retry_ratio ở 0,058 thay vì
0,499, tức gần 9× ít retry hơn, và amplification dưới ngưỡng 1,6. Khi breaker *hoạt động đúng*, tắt budget không đổi
gì (G2: 1,055 / 0,007 cả hai trường hợp), vì breaker đã mở và call đi fail over trước khi kịp xin token. Vẫn nên có cả
hai vì chúng bảo vệ ở hai tầng khác nhau:
- Breaker là tín hiệu *theo từng provider*, phụ thuộc tham số (window, ngưỡng) nên có thể cấu hình sai, hoặc không trip
  khi lỗi nằm ngay dưới ngưỡng (G3: 30% < 50%).
- Budget là giới hạn *tổng* rẻ tiền, không cần hiểu nguyên nhân. Nó đảm bảo trong trường hợp xấu nhất tải retry
  ≤ 10% traffic.

**2. `attempt_timeout_s: 30`.**

| Băng | timeout | availability | give_up_reasons | p95 (s) |
|---|---:|---:|---|---:|
| G6 | 8 | 0,9904 | no_provider_available: 23 | 5,94 |
| G6 | 30 | **0,9438** (< 0,95: FAIL) | **deadline: 107**, no_provider_available: 27 | 5,41 |
| G4 | 8 | 1,0 | – | 5,63 |
| G4 | 30 | 1,0 | – | 5,68 |

Ở G6, `alpha-eu` *treo* chứ không trả lỗi. Với timeout 30 s, một call bị kẹt ở đó dùng hết deadline 30 s của user
trước khi kịp fail over sang beta, nên 107 lượt chết vì `deadline`. p95 lại *giảm* (5,94 → 5,41 s) vì chỉ tính lượt
thành công: những lượt bị treo đã chết và không còn nằm trong mẫu (survivorship bias). G4 gần như không đổi vì ở đó
alpha vẫn trả lời, chỉ chậm khoảng 6 s. Không có call nào chạm timeout 8 s, và slow-call breaker đã chuyển traffic
đi trước khi timeout có ý nghĩa. Timeout đúng nên lấy từ **cả ba**:
- Cận dưới là p99 lúc bình thường, khoảng vài giây, để không cắt nhầm call khỏe.
- Cận trên là deadline của user trừ đi thời gian cần cho ít nhất 1–2 lần fail over, khoảng 30 − 2×(timeout + p50 của
  provider dự phòng).

8 s thỏa cả hai.

**3. Bỏ lọc tool calling khỏi `ladder()`** (G6): availability 0,9933 → **0,8977**, `incompatible_routes = 244`,
`give_up_reasons = {incompatible_model_output: 244}`. Nói theo ngôn ngữ product: khi provider chính sập, có 244 khách
hàng đang yêu cầu hoàn tiền bị chuyển sang một model "rẻ nhưng không biết dùng công cụ". Model này không tra được đơn
hàng, cũng không tạo được lệnh hoàn tiền, nên khách nhận câu trả lời hỏng thay vì được xử lý. Hệ thống trông như "vẫn
trả lời" nhưng thực chất đã làm hỏng ~10% lượt trong sự cố, tệ hơn cả việc báo lỗi và chờ beta.

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1,0 | 81 | 128 | 81 | 0 | 1.496.700 cents | 1,123 |
| yours | 1,0 | 66 | **0** | **0** | **0** | **0** | **0,303** |

- **Chỉ idempotency key thì chưa đủ.** Payment và email không bị trùng, nhưng mỗi worker mới chạy lại từ đầu: gọi lại
  LLM `classify`, lại `lookup_order`… nên tốn tiền (wasted LLM/crash của naive là 1,12). Nếu bước LLM không tất định,
  worker mới có thể sinh payload khác cho cùng key, gây `IdempotencyConflict` hoặc kết quả lệch.
- **Chỉ checkpoint thì chưa đủ.** Cửa sổ nguy hiểm là lúc *payment đã chạy nhưng checkpoint chưa ghi*: response bị mất
  (`ServiceTimeout`) hoặc worker chết ngay sau khi tiền đã đi (`WorkerCrash`). Worker mới không thấy checkpoint nên gọi
  refund lần nữa. Không có key ổn định `session:step` thì đó là hoàn tiền trùng; naive có 128 lần, trả thừa 14.967 USD.
- **Ghi checkpoint *trước* khi gọi payment:** nếu worker chết hoặc payment lỗi sau khi đã ghi, worker mới thấy bước
  `issue_refund` "đã xong" và bỏ qua. Khách **không bao giờ được hoàn tiền** (lost refund), và `send_email` báo
  "đã hoàn tiền" cho một khoản không tồn tại. Thứ tự đúng là: thực thi (với key ổn định) → checkpoint → bước kế tiếp.
  Khi crash nằm giữa hai việc này, bước bị chạy lại nhưng idempotency key biến lần chạy lại thành no-op.

## 5. Alerting & error budget

| Sự cố | Mong đợi | Naive alerter | Burn-rate alerter | Độ trễ phát hiện (burn-rate) |
|---|---|---|---|---:|
| checkout_bug | page | page (1 phút) | ✅ page | 27 phút (hạn 35) |
| provider_outage | page | page (0 phút) | ✅ page | 4 phút (hạn 8) |
| deploy_blip | none | ❌ page sai | ✅ im lặng | – |
| slow_leak | ticket | ❌ không phát hiện | ✅ ticket, không page | 1.337 phút (hạn 1.800) |
| degraded_evening | page | page (214 phút) | ✅ page | 291 phút (hạn 330) |
| night_spike | none | ❌ page sai | ✅ im lặng | – |
| small_bump | none | ❌ page sai | ✅ im lặng | – |

Naive: 7 page, 3 false page, FAIL. Burn-rate: 3 page, 1 ticket, 0 false page, PASS. Tôi kiểm tra thêm trên 20 seed dữ
liệu khác của `generate()`: 0 lần FAIL.

**Error budget 30 ngày:** 25.901.755 request; budget cho phép 129.508,8 lỗi; thực tế 55.618 lỗi (availability 99,785%).
**Đã tiêu 42,95%, còn 57,05%, nên không đóng băng release** (`freeze_releases: false`). Vẫn nên ưu tiên sửa `slow_leak`,
vì nó một mình đốt khoảng 1,5%/0,5% = 3× tốc độ cho phép trong 2 ngày.

**Vì sao `small_bump` không nên đánh thức ai:** 20 phút ở 12% lỗi chỉ tiêu ~1% error budget tháng. Burn rate 1h trung
bình ≈ 12%×20/60 / 0,5% = 8× < 14,4, và nó tự hết. Page là để đòi người hành động *ngay*. Sự cố này không đe dọa
SLO, nên page sẽ chỉ làm on-call mệt và quen bỏ qua alert (alert fatigue). Dashboard và error budget đã đủ để ghi
nhận nó.

## 6. Postmortem — Băng G2 với client naive (blameless)

![G2 naive vs resilient](gameday/G2_overload_storm.png)

**Tóm tắt:** Lúc t=120 s, deployment `alpha` mất 75% năng lực GPU trong 3 phút. Client v1 có 3 tầng retry chồng nhau
(tối đa 36 attempt/call, delay cố định 0,2 s), nên lượng attempt gửi tới alpha tăng từ ~8/s lên ~250/s. Hệ thống không
có call nào thành công từ t=137 đến t=452 (315 s), tức vẫn sập thêm **152 s sau khi alpha đã hồi phục hoàn toàn**
(t=300).

**Ảnh hưởng:**
- 1.285 / 2.362 lượt user thất bại (availability 45,6%), p95 của lượt thành công 15 s.
- Khoảng 5 phút 15 giây hoàn toàn không phục vụ được, cho một sự cố hạ tầng chỉ dài 3 phút.
- 34.475 attempt cho 3.481 call (amplification 9,9×). Chi phí trên mỗi lượt tốt gấp 2,2 lần (4,63 so với 2,12).
- Error budget: một tháng ở 4 lượt/s là ~10,37 triệu lượt, budget 99,5% là ~51.840 lượt lỗi. Sự cố này một mình tiêu
  ~2,5% budget tháng trong 10 phút. Burn rate trong cửa sổ sự cố ≈ 54,4% / 0,5% ≈ 109×, đủ cho page 14,4× bắn trong
  vài phút.

**Timeline** (giây ảo, từ `naive_G2_overload_storm_timeseries.csv`; "ok/s" = call thành công mỗi giây):

| t | Sự kiện | Bằng chứng (số) |
|---:|---|---|
| 0–120 | Bình thường | ~7,5 ok/s, ~7,5 attempt/s vào alpha (amplification ≈ 1) |
| 120 | alpha mất 75% năng lực (18 → ~4,5 slot) | ok/s rơi từ 7–10 xuống 0–4 trong t=121–135 |
| 133–143 | Retry bùng nổ: mỗi lỗi 529/timeout sinh retry sau 0,2 s, không jitter, không budget | attempt/s: 15 (t=133) → 82 (t=137) → 176 (t=139) → **254 (t=143, đỉnh)** |
| 137 | Sập hoàn toàn | ok/s = 0 từ t=137, liên tục |
| 140–300 | Bão tự duy trì: hầu hết attempt dính 429 vì vượt rate limit 20 rps của tenant, chính client tự rate-limit mình. Phần lọt qua thì xếp hàng >10 s → 529, hoặc timeout 8 s → retry | ~140–150 attempt/s, 0 ok/s; tổng 26.298 lỗi 429 và 28.381 vi phạm retry-after |
| 300 | alpha hồi phục hoàn toàn | attempt/s giảm 149 → 36 (t=303) vì nhiều call đã hết 36 attempt hoặc hết deadline |
| 300–452 | **Vẫn sập dù provider đã khỏe**: hàng đợi đầy request mà client đã bỏ (server vẫn xử lý), mỗi call mới vào sau hàng đợi đó, timeout ở 8 s rồi retry tiếp; lượng retry đẩy tải ≥ năng lực (~15 req/s) | 0 ok/s; attempt/s dao động 6–76 (đỉnh phụ ~76/s ở t=340–400) |
| 453 | Hàng đợi cuối cùng cũng rút, thành công trở lại | ok/s 4 (t=453) → 8 (t=456) → 12 (t=461) |
| 455 | Hồi phục theo định nghĩa (95% call OK trong 30 s) | `recovery_s = 155` (từ t=300) |
| 460–600 | Bình thường trở lại | ~8–12 ok/s, ~8–10 attempt/s |

**Trigger vs root cause:**
- **Trigger:** alpha mất 75% GPU trong 3 phút. Đây là sự kiện bên ngoài, sẽ còn xảy ra.
- **Root cause:** lớp gọi LLM khuếch đại lỗi thay vì hấp thụ nó:
  - 3 tầng retry độc lập (app × gateway × SDK = 36 attempt/call), delay cố định không jitter;
  - không tôn trọng `retry-after`, không có retry budget, không có circuit breaker, không fail over sang
    `alpha-eu`/`beta` đang rảnh;
  - không biết deadline của user.
- **Vòng lặp metastable:** năng lực giảm → latency tăng → timeout/529 → retry ×36 → tải tăng → latency tăng hơn nữa.
  - Khi trigger biến mất ở t=300, vòng lặp vẫn tự duy trì. Hàng đợi chứa đầy request mà client đã bỏ, server vẫn tốn
    slot xử lý chúng (công sức bị phí), nên request mới lại timeout và lại retry. Tải từ retry giữ ở mức ≥ năng lực
    đã phục hồi.
  - Hệ thống chỉ thoát ra khi đủ nhiều call dùng hết 36 attempt hoặc hết deadline 30 s (655 `retries_exhausted`,
    585 `deadline`) và hàng đợi rút được.

**Điều gì giúp / điều gì làm tệ hơn:**
- *Giúp:* giới hạn cứng 36 attempt/call và deadline 30 s của user cuối cùng cũng cắt được vòng lặp. Rate limit 20 rps
  của tenant (429 trả ngay) che cho alpha khỏi phải xử lý ~250 req/s thật. Provider tự hồi phục đúng t=300.
- *Làm tệ hơn:*
  - Retry với delay cố định 0,2 s làm mọi client quay lại cùng lúc.
  - Retry ngay cả lỗi 429 dù có `retry-after`.
  - Timeout 8 s ở client trong khi server vẫn xử lý request đã bị bỏ.
  - Không có fail over: `alpha-eu` và `beta` nhàn rỗi suốt 5 phút (0 attempt).
  - Không có tín hiệu nào báo "dừng gửi" (breaker).

**Action items:**

| # | Hành động | Loại | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Thay `NaiveClient` bằng `ResilientClient`: đúng 1 tầng retry, full jitter, tôn trọng `retry-after`, retry budget 10% | prevent | Team platform LLM (on-call lead) | CI chạy G2 trên 3 seed + băng ẩn: amplification ≤ 1,2 (hiện 1,04), retry_after_violations = 0 |
| 2 | Circuit breaker sliding-window theo từng deployment + fallback ladder alpha → alpha-eu → beta (lọc tool calling) | mitigate | Team platform LLM | G2 recovery_s ≤ 30 (hiện 0), availability ≥ 95% (hiện 100%), G6 incompatible_routes = 0 |
| 3 | Tắt retry ở gateway và SDK (`max_retries=0`), chỉ giữ retry ở tầng client; thêm lint/test cấm cấu hình retry ở tầng khác | prevent | Team gateway | Test cấu hình trong CI; số attempt/call tối đa đo được trên G2 ≤ 4 |
| 4 | Alert burn-rate đa cửa sổ (14,4× 1h&5m, 6× 6h&30m) + alert riêng khi `amplification` > 1,5 trong 5 phút | detect | SRE on-call | Replay CSV G2: page bắn trong ≤ 5 phút sau t=120; 0 false page trên `data/sli_30d.csv` |
| 5 | Game day hằng quý với 6 băng sự cố; mỗi thay đổi client phải PASS `make compare` trước khi deploy | prevent | Eng manager team agent | Biên bản game day; CI gate trên `make grade` ≥ 84/88 |

Postmortem này tập trung vào hệ thống và quy trình: cấu hình retry nhiều tầng là mặc định phổ biến của từng thư viện,
không ai chủ động thiết kế nó. Lỗ hổng là thiếu một nơi duy nhất sở hữu chính sách retry, và thiếu game day để lộ ra
hành vi khuếch đại trước khi production gặp.

## 7. Một điểm yếu còn lại

**p95 ở G2 vẫn cao (10,7 s, so với 4,7 s ở G1/G3).** Khi alpha chỉ chậm dần (hàng đợi dài nhưng chưa 529), các call
đầu tiên vẫn vào alpha và phải chờ tới timeout 8 s, cho đến khi breaker gom đủ `min_calls=10` kết quả xấu để trip. Mỗi
lần breaker HALF_OPEN dò lại trong lúc alpha còn yếu cũng làm vài call chịu thêm 8 s. Cách sửa:
1. **Hedged request / timeout thích nghi:** timeout = max(2 s, k × p99 trượt của từng provider) thay vì cố định 8 s.
   Khi provider chậm bất thường thì cắt sớm và fail over.
2. **Load-aware routing:** khi alpha có latency p50 gần đây tăng gấp 2–3 lần, chủ động chia một phần traffic sang
   alpha-eu (cùng model, cùng chi phí) trước khi breaker trip.

Kiểm chứng: G2 p95 ≤ 6 s, primary share sau hồi phục vẫn ≥ 0,8, amplification ≤ 1,2.

Một điểm yếu nữa là **chi phí ở G5** (2,50/turn so với 2,12 lúc bình thường): khi account A hết quota, toàn bộ tool
call phải đi beta (1,4×). Đó là đánh đổi chấp nhận được, nhưng nên có alert quota sớm (dự báo ngày hết credit) để nạp
trước.

## 8. Cache (Part G)

Số từ `reports/cache/*.json` (`make cache`, seed 25):

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0,8373 | 0,8424 | 0,0 | 0 | 0 | 0 | 1,386 | ❌ faq_availability, hit ratio |
| cached (của bạn) | 0,9124 | **0,9645** | **0,652** | 157 | **0** | **3** | **0,915** | ✅ |

Cache giảm chi phí 34% (1,386 → 0,915/turn) và giữ FAQ sống qua 2 phút mọi provider sập. Cấu hình PASS trên 6/6 seed
(1–6) và 3/3 seed của grader (25, 26, 27).

| Tham số `cache:` | Giá trị | Vì sao (số liệu nào) |
|---|---:|---|
| similarity_threshold | 0,92 | Đo trên catalog FAQ: paraphrase cùng ý có cosine **0,951–0,984**, cặp khác ý "gần mà khác" cao nhất **0,862**. 0,92 nằm giữa khoảng hở, cách cả hai phía ≥ 0,03. Ở 0,80: 157 `other_question`. Ở 0,92: 0 |
| ttl_s | 60 | Giới hạn thay đổi không báo trước (bảng phí ship đổi ở t=480): outdated = 3 (≤ 8 trên 6 seed). TTL 90 s đã FAIL 3/6 seed (outdated tới 28), 300 s cho outdated 95. TTL 30 s làm hit ratio tụt còn 0,567 ở seed xấu nhất, sát ngưỡng 0,5 |
| max_stale_s | 600 | Phải dài hơn TTL + thời gian sự cố (60 + 120 s) để entry còn dùng được suốt lúc mọi provider sập; 600 s chừa biên cho sự cố dài gấp 3–4 lần. Ở 0: faq_availability 0,873 (FAIL) so với 0,9645 |
| max_entries | 500 | Catalog chỉ có ~18 ý shared × vài paraphrase × 2 prompt version, nên 500 không bao giờ phải evict trên băng này. Vẫn có LRU để bộ nhớ có giới hạn |

**Thí nghiệm:**

1. **Ngưỡng** (TTL 60, stale 600):

   | threshold | hit ratio | wrong_answers | cost/turn | faq_availability |
   |---:|---:|---:|---:|---:|
   | 0,80 | 0,666 | **157** (`other_question`) | 0,965 | 0,873 |
   | 0,92 (của tôi) | 0,652 | 0 | 0,915 | 0,9645 |
   | 0,97 | 0,581 | 0 | 0,964 | 0,964 |

   Ở 0,80, các cặp ý "gần mà khác" (cosine ~0,86) bị gộp:
   - "Chính sách hoàn tiền" ↔ "Bao lâu thì nhận tiền hoàn"
   - "Đổi size" ↔ "Đổi màu"
   - "Phí ship nội thành" ↔ "Phí ship đi tỉnh"
   - "Hình thức thanh toán" ↔ "COD"

   Khách hỏi phí ship đi tỉnh nhận giá nội thành. Hit ratio cao hơn không có giá trị khi câu trả lời sai. Ở 0,97, một
   số paraphrase thật (0,951–0,97) không còn khớp nhau, nên hit giảm và cost tăng lại 0,964.

2. **TTL** (threshold 0,92, stale 600):

   | ttl_s | hit ratio | outdated_answers | stale_served |
   |---:|---:|---:|---:|
   | 30 | 0,592 | 2 | 192 |
   | 60 | 0,652 | 3 | 157 |
   | 300 | 0,731 | **95** (> 15: FAIL) | 69 |

   Webhook không giúp được `outdated_answers` vì bảng phí ship đổi **không có webhook** (nhà vận chuyển đổi giá, CMS
   không biết). Cache không có tín hiệu nào để biết entry đã sai, nên chỉ tuổi của entry (TTL) giới hạn được thời gian
   một câu trả lời cũ còn được phục vụ. Số câu outdated ≈ tần suất hỏi × TTL.

3. **Stale-if-error** (`max_stale_s: 0`): faq_availability **0,9645 → 0,873** (FAIL), stale_served 157 → 0. Khi mọi
   provider sập (t=240–360), không có stale thì mọi câu FAQ ngoài TTL 60 s đều thất bại. Có stale, 157 lượt được trả
   bằng câu trả lời cũ nhưng vẫn đúng.

**Trả lời:**

- **Vì sao không cache câu hỏi cá nhân, kể cả theo từng user:**
  - Embedding của "Đơn #48213 của tôi ở đâu?" và "Đơn #48214…" giống nhau ~0,99, vì số đơn chỉ đẩy vector đi rất ít.
    Cache semantic theo similarity sẽ trả đơn của người này cho người khác, tức lộ dữ liệu cá nhân (`other_user`).
  - Kể cả khi scope theo user, câu trả lời phụ thuộc trạng thái **thay đổi liên tục** (đơn đang giao, tiền hoàn đã về
    chưa) mà không có webhook nào báo cache. Câu trả lời cũ về tiền bạc/đơn hàng là sai và gây hại: khách tưởng tiền
    đã về.
  - Những câu này cũng hiếm khi lặp lại, nên hit ratio gần 0: rủi ro cao, lợi ích ≈ 0. Hướng đúng là gọi thẳng
    tool/DB (rẻ và tươi), không cache câu trả lời LLM.
- **Dashboard xanh nhờ cache, alert dựa trên gì:** alert trên **sức khỏe provider và tỷ lệ phục vụ stale**, không chỉ
  trên availability mà user thấy:
  - `stale_served / cache_served` (hoặc số stale/phút) > 0 kéo dài vài phút, nghĩa là đang sống nhờ bậc 3 của
    fallback ladder;
  - tỷ lệ `GiveUp` của `ResilientClient` bên trong / tỷ lệ lỗi provider (SLI "upstream availability");
  - tỷ lệ thất bại của lượt **không cache được** (tool call, câu hỏi cá nhân). Ở C1 availability tổng vẫn tụt
    (0,9124 so với faq 0,9645).

  Page khi burn-rate của SLI upstream vượt ngưỡng, kể cả khi SLI phía user vẫn xanh, vì stale có hạn (600 s) và mọi
  thay đổi nội dung trong lúc đó sẽ không được cập nhật.
