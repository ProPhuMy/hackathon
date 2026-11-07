# **Fridge Tracker – Project Overview**

Cập nhật 07/11/2026 · Dang  
**Một câu:** hệ thống quản lý tủ lạnh chung, biết ai đặt gì, ai lấy gì, và ai lấy nhầm đồ của người khác. Mọi kỹ thuật thêm vào phải làm câu này chính xác hơn, hoặc giúp truy cập dữ liệu của câu này.

## **Bài toán và mục tiêu**

Hệ thống theo dõi tủ lạnh chung: biết ai đặt món nào vào, ai lấy món nào ra, và báo khi người lấy không phải chủ món đồ. Mọi thứ được quản trị qua một web dashboard.  
Dự thi track **Most Over-Engineered**. Nguyên tắc: thuật toán được phép phức tạp, nhưng mỗi lớp phải phục vụ một mục tiêu cụ thể, chủ yếu là tăng độ chính xác của nhận diện người.  
Bối cảnh dùng để pitch (đề xuất, team chưa chốt): tủ lạnh chung ở ký túc xá, nhà share hoặc pantry văn phòng.

## **Phạm vi đã chốt**

Dự án có đúng 6 chức năng dưới đây. Chức năng nào không nằm trong bảng thì không làm, trừ khi cả team đồng ý thay một dòng cũ.

| \# | Chức năng | Làm được gì | Xong khi (đề xuất) |
| :---- | :---- | :---- | :---- |
| 1 | Ghi nhận người đặt đồ | Biết ai vừa đặt món nào vào tủ | Mỗi lần đặt sinh ra một sự kiện PUT có người, món, thời gian |
| 2 | Ghi nhận người lấy đồ | Biết ai vừa lấy món nào ra khỏi tủ | Mỗi lần lấy sinh ra một sự kiện TAKE tương tự |
| 3 | Tồn kho hiện tại | Danh sách món đang có trong tủ và chủ của từng món | Danh sách khớp với thực tế sau mỗi lần đóng cửa |
| 4 | Matching và cảnh báo | So người lấy với chủ món đồ, báo khi khác nhau | Lấy nhầm đồ thì dashboard hiện cảnh báo; điểm tin cậy thấp thì đánh dấu "không chắc" |
| 5 | Web dashboard | Quản trị người dùng, tồn kho, lịch sử sự kiện, cảnh báo | Xem được cả 4 thứ đó và đăng ký được người mới |
| 6 | Nhận diện và tracking khuôn mặt độ chính xác cao | Xác định đúng người cho chức năng 1 và 2 | Có số đo accuracy trên bộ test của team |

Các lớp thuật toán ở phần Kiến trúc (tracking, gộp embedding, open-set, liveness) là **cách làm chức năng 6**, không phải chức năng mới. Độ phức tạp cho track over-engineered nằm bên trong chức năng 6, không nằm ở việc thêm tính năng.  
**MCP server** là một lớp truy cập, không phải chức năng mới: nó cho các Claude khác đọc tồn kho, lịch sử, cảnh báo và xu hướng từ cùng dữ liệu với dashboard. Chỉ đọc, không trả về ảnh mặt hay embedding. Tool dự kiến: get\_inventory, get\_history, get\_alerts, get\_trends.

## **Kiến trúc kỹ thuật**

Người và món đồ được nhận diện song song, rồi gộp lại để matching. Chỉ khi cả hai luồng có kết quả thì mới sinh sự kiện và đưa vào matching.  
**Luồng nhận diện người (chức năng 6\)**

> 1. Camera Galaxy Z Flip: stream video về Mac  
> 2. Phát hiện và căn mặt: ensemble SCRFD \+ YOLO-face (WBF)  
> 3. Embedding khuôn mặt: ensemble ArcFace \+ AdaFace, có calibration  
> 4. Tracking và gộp theo thời gian: BoT-SORT; gộp theo điểm chất lượng MagFace  
> 5. Liveness (chưa chốt): chống giơ ảnh; chỉ làm nếu còn giờ  
> 6. Ai đây? Conformal prediction: người quen hay người lạ

**Luồng nhận diện món đồ**

> 1. Cửa mở (chưa chốt): camera món đồ phát hiện đèn tủ bật  
> 2. Tay \+ vật: Grounding DINO \+ SAM 2; tay 3D bằng HaMeR  
> 3. Vào hay ra, cầm hay chạm: mặt phẳng 3D ở cửa \+ Transformer phân loại hành động  
> 4. Món nào, của ai: DINOv2 \+ màu \+ vị trí, ghép bằng Hungarian algorithm

**Hai luồng gộp lại**

> 1. Sự kiện PUT / TAKE: người \+ món \+ thời gian \+ điểm tin cậy (chức năng 1, 2\)  
> 2. Matching \+ cảnh báo (chức năng 4): lấy nhầm thì cảnh báo; điểm thấp thì đánh dấu "không chắc"  
> 3. Web dashboard (chức năng 3, 5): tồn kho, lịch sử sự kiện, cảnh báo, đăng ký người

## **Kỹ thuật over-engineer theo từng vấn đề**

Mỗi kỹ thuật thay một cách làm đơn giản và sửa đúng một lỗi của cách đó. Cột "Sửa lỗi gì" chính là lý do để nói với giám khảo, và mỗi lớp nên có số đo accuracy khi bật và tắt.  
**Lưu ý:** các kỹ thuật dưới đây chỉ là gợi ý, chưa phải lựa chọn cuối cùng. Mỗi thành viên research phần mình phụ trách, có thể thay bằng kỹ thuật khác nếu tốt hơn, miễn vẫn sửa đúng lỗi ghi ở cột cuối. Khi research, kiểm tra 4 điểm:

> * Có code và model pretrained sẵn không  
> * Chạy được trên Mac (Apple Silicon) không, tốn bao nhiêu RAM  
> * Tốc độ xử lý mỗi frame  
> * Độ khó tích hợp trong thời gian hackathon

### **Nhận diện người**

| Vấn đề | Thay vì | Dùng | Sửa lỗi gì |
| :---- | :---- | :---- | :---- |
| Phát hiện mặt | SCRFD | Ensemble SCRFD \+ YOLO-face, gộp bằng Weighted Boxes Fusion | Sót mặt nghiêng, mặt nhỏ ở xa |
| Nhận diện mặt | ArcFace | Ensemble ArcFace \+ AdaFace, gộp điểm qua calibration; norm của MagFace làm điểm chất lượng frame | Frame mờ, thiếu sáng làm sai danh tính |
| Người lạ | Một ngưỡng cố định | Conformal prediction: ngưỡng có đảm bảo tỷ lệ lỗi | Gán bừa người lạ thành người quen |
| Tracking | ByteTrack | BoT-SORT có bù chuyển động camera | Mất ID khi bị che hoặc điện thoại rung |
| Quay lưng vào tủ | Không xử lý | Không làm: team đã bỏ body re-ID | Mất danh tính đúng lúc thao tác với tủ |
| Giơ ảnh giả | Không xử lý | Depth Anything V2 (ảnh phẳng không có chiều sâu) \+ rPPG đo nhịp tim qua màu da | Giả mạo bằng ảnh hoặc video trên điện thoại |

### **Tay \+ vật**

| Vấn đề | Thay vì | Dùng | Sửa lỗi gì |
| :---- | :---- | :---- | :---- |
| Cửa mở | Công tắc bật/tắt | Camera món đồ phát hiện đèn trong tủ bật \+ optical flow trên cánh cửa (đề xuất) | Xử lý thừa khi không ai mở tủ |
| Phát hiện vật | YOLO với lớp cố định | Grounding DINO (open-vocabulary) \+ SAM 2 theo dõi mask qua video | Món lạ không có trong lớp; vật bị tay che |
| Bàn tay | MediaPipe Hands 2D | HaMeR dựng mesh tay 3D | Không biết tay có thật sự nắm vật không |
| Tay của ai | Không xử lý | Pose toàn thân (ViTPose), nối cổ tay của skeleton với bàn tay | Hai người đứng gần tủ cùng lúc |
| Vào hay ra | So ảnh trước/sau | Depth Anything V2 dựng mặt phẳng 3D ở cửa tủ; quỹ đạo vật qua Kalman filter | Không biết hướng PUT hay TAKE |
| Loại hành động | Luật if/else | Transformer trên chuỗi keypoint tay \+ mask vật, phân loại PUT / TAKE / chỉ chạm | Chạm rồi để lại bị tính là lấy |
| Món nào, của ai | Sticker QR | DINOv2 \+ histogram màu \+ vị trí kệ, ghép bằng Hungarian algorithm | Hai món giống hệt nhau |
| Nhất quán | Tin từng sự kiện riêng lẻ | Factor graph trên chuỗi sự kiện, ví dụ không thể lấy món không có trong tủ | Sự kiện mâu thuẫn nhau |

### **Hạ tầng**

| Vấn đề | Thay vì | Dùng | Sửa lỗi gì |
| :---- | :---- | :---- | :---- |
| Điều phối | Một script Python | Kubernetes (k3d trên Mac), mỗi model một microservice | Một model chậm kéo cả hệ thống |
| Truyền dữ liệu | Gọi hàm trực tiếp | Redpanda (tương thích Kafka) làm event bus | Rớt frame khi model xử lý không kịp |
| Lưu trạng thái | Một bảng tồn kho | Event sourcing \+ CQRS: tồn kho là phép chiếu từ log sự kiện | Mất lịch sử mà trends và MCP cần |
| Serving model | Load model trong từng service | Ray Serve có dynamic batching | Xử lý từng frame lẻ, phí phần cứng |
| Autoscale | Số worker cố định | KEDA scale worker theo consumer lag | Nhiều tủ, nhiều người cùng lúc |
| Gallery khuôn mặt | List trong RAM | Qdrant (vector DB) | Tìm kiếm chậm khi nhiều người |
| Trends | Query thẳng log | TimescaleDB | Truy vấn xu hướng theo thời gian |
| Bảo mật | Không mã hóa nội bộ | Linkerd service mesh, mTLS giữa các service | Dữ liệu khuôn mặt đi qua mạng nội bộ không mã hóa |
| Quan sát | print log | OpenTelemetry tracing \+ Prometheus/Grafana | Không biết sự kiện bị chậm ở bước nào |
| Triển khai | kubectl apply bằng tay | GitOps với Argo CD | Thuần over-engineer, nói thẳng điều đó khi pitch |

### **Thiết kế hệ thống phân tán**

Bảng Hạ tầng ở trên là công cụ; bảng này là thuật toán của hệ thống phân tán chạy trên các công cụ đó. Mỗi dòng vẫn sửa một lỗi thật của một hệ thống có hai camera và nhiều service.

| Vấn đề | Thay vì | Dùng | Sửa lỗi gì |
| :---- | :---- | :---- | :---- |
| Ghép người với món | So timestamp trực tiếp | Event-time window join có watermark (Quix Streams hoặc Bytewax), xử lý sự kiện đến trễ | Mạng trễ làm sự kiện đến sai thứ tự, ghép nhầm người |
| Đồng hồ hai camera | Tin giờ của điện thoại | Hybrid logical clock gắn vào mỗi frame, ước lượng độ lệch đồng hồ lúc khởi động | Hai điện thoại lệch giờ vài trăm mili giây |
| Xử lý trùng | Ghi thẳng | Idempotency key cho mỗi sự kiện \+ Kafka transactions (exactly-once) | Một lần lấy đồ bị tính hai lần khi service khởi động lại |
| Ghi DB và publish | Hai lệnh riêng | Transactional outbox | DB và event bus lệch nhau khi crash giữa chừng |
| Thứ tự theo tủ | Một topic chung | Partition theo fridge\_id, consistent hashing gán tủ cho worker | Sự kiện cùng một tủ bị xử lý lộn thứ tự khi scale |
| Model xử lý không kịp | Chờ | Back-pressure: hàng đợi ưu tiên theo điểm chất lượng frame, bỏ frame kém trước (load shedding) | Hàng đợi phình ra, độ trễ tăng mãi |
| Model bị lỗi | Cả luồng đứng | Circuit breaker \+ graceful degradation: SAM 2 lỗi thì tự quay về YOLO | Một model lỗi làm sập cả hệ thống |
| Nâng cấp model | Thay thẳng | Không làm: dùng script đo accuracy trên bộ clip test | Không biết model mới có tốt hơn không; cũng là nguồn số accuracy bật/tắt |
| Event bus | Một broker | Cluster Redpanda 3 node, mỗi partition nhân bản bằng Raft | Một broker chết là mất sự kiện |
| Hợp đồng sự kiện | JSON tự do | Schema registry của Redpanda \+ Protobuf | Một người đổi định dạng làm vỡ service của người khác |
| Độ bền | Hy vọng nó chạy | Chaos engineering: tự động kill pod hoặc broker ngẫu nhiên khi đang chạy | Chứng minh hệ thống tự hồi phục |
| MCP server | Gọi không giới hạn | Token bucket rate limiting | AI khác gọi dồn dập làm chậm dashboard |

Đã chốt: làm watermark join, không làm shadow deployment. Cluster Redpanda 3 node kèm chaos test cũng làm, sau khi luồng chính đã chạy với 1 node; cả 3 node chạy trên cùng một Mac nên đây là mô phỏng phân tán, nói rõ điều này trong video.  
Câu chuyện để pitch: các model nặng (SAM 2, HaMeR, ensemble) làm hệ thống chậm, nên cần event bus, Kubernetes và autoscale. Độ phức tạp của hạ tầng được chính độ phức tạp của thuật toán biện minh.  
Rủi ro thật: nhiều model trong bảng vốn viết cho GPU NVIDIA, nên cần thử từng cái trên Apple Silicon (MPS) trước khi chốt. RAM của Mac là giới hạn khi chạy cùng lúc k3d, Redpanda và vài model.

## **Thứ tự ưu tiên**

Làm theo thứ tự này; mỗi bước chỉ bắt đầu khi bước trước đã chạy được.

> 1. Luồng chính chạy trọn vẹn: một người, một món, đặt vào rồi lấy ra, hiện lên dashboard.  
> 2. Các lớp chính xác cho nhận diện người và tay \+ vật (hai bảng đầu ở trên).  
> 3. MCP server.  
> 4. Hạ tầng cluster (bảng Hạ tầng).

Nếu hết giờ, cắt hạ tầng trước: nó làm hệ thống trông to hơn chứ không làm hệ thống đúng hơn.

## **Chia việc**

Bốn vai chạy song song, nối với nhau bằng một định dạng sự kiện chung chốt trong 30 phút đầu. Gán người là đề xuất, team có thể đổi.

| Vai | Người | Phụ trách | Bàn giao |
| :---- | :---- | :---- | :---- |
| 1\. Nhận diện người | Thành viên 2 | Camera mặt, ensemble detection, ArcFace \+ AdaFace, BoT-SORT, open-set | Sự kiện person.seen |
| 2\. Nhận diện món đồ | Thành viên 3 | Camera món, phát hiện cửa mở, Grounding DINO \+ SAM 2, HaMeR, phân loại PUT/TAKE, DINOv2 \+ Hungarian | Sự kiện item.event |
| 3\. Backend và matching | Dang (đề xuất) | Event bus, event sourcing \+ CQRS, ghép người với sự kiện món đồ theo thời gian, matching \+ cảnh báo, MCP server | API cho dashboard và MCP |
| 4\. Dashboard, hạ tầng và video | Thành viên 4 | Web dashboard, Kubernetes \+ autoscale, Grafana, quay và dựng video demo | Video nộp lúc 13:00 |

Hai luồng nhận diện không biết về nhau; backend ghép chúng theo cửa sổ thời gian thành fridge.event. Định dạng đề xuất:  
`{ "topic": "person.seen", "track_id": 7, "person_id": "p_02", "ts": "2026-11-08T09:15:02.120Z", "confidence": 0.93 }`  
`{ "topic": "item.event", "type": "TAKE", "item_id": "item_042", "item_label": "hộp sữa", "ts": "2026-11-08T09:15:03.480Z", "confidence": 0.88 }`  
Các mốc:

> 1. 30 phút đầu: chốt định dạng sự kiện. Mỗi người dùng dữ liệu giả theo định dạng đó để không phải chờ nhau.  
> 2. Luồng chính chạy trọn vẹn với model đơn giản nhất.  
> 3. Thay dần bằng kỹ thuật over-engineer, đo accuracy trước và sau mỗi lần thay.  
> 4. Khoảng 10:00 sáng 8/11: đóng băng code, cả team chuyển sang quay và dựng video.  
> 5. 13:00: nộp.

Trong lúc làm, mỗi người lưu lại video debug của phần mình (bounding box, mask, track ID, mesh tay). Đó là cảnh quay sẵn cho đoạn giới thiệu thuật toán.

## **Triển khai**

Bắt đầu bằng docker-compose và dữ liệu giả để cả 4 người làm song song ngay. Kubernetes chỉ vào sau khi luồng chính đã chạy.

### **Stack**

| Lớp | Công cụ |
| :---- | :---- |
| Ngôn ngữ | Python 3.11 \+ uv cho mọi service vision và backend |
| Video từ điện thoại | Android: app IP Webcam stream MJPEG qua Wi-Fi, đọc bằng OpenCV; iPhone: Continuity Camera với Mac |
| Nhận diện người | insightface (SCRFD, ArcFace), boxmot (BoT-SORT) |
| Nhận diện món đồ | ultralytics YOLO và MediaPipe Hands cho bản đầu; transformers (Grounding DINO, DINOv2) và SAM 2 khi nâng cấp |
| Event bus | Redpanda trong Docker |
| Backend | FastAPI, Postgres làm event store, SSE đẩy cập nhật sang dashboard |
| MCP server | Python MCP SDK (FastMCP), chỉ đọc |
| Dashboard | React (Vite) |
| Hạ tầng | docker-compose trước; sau đó k3d \+ KEDA \+ Prometheus/Grafana |

### **Cấu trúc repo**

`fridge/`  
  `contracts/              # định dạng sự kiện (JSON Schema), chốt đầu tiên`  
  `tools/fake_events.py    # bắn sự kiện giả để không ai phải chờ ai`  
  `services/person/        # Vai 1`  
  `services/item/          # Vai 2`  
  `services/backend/       # Vai 3: ghép sự kiện, matching, API, MCP`  
  `dashboard/              # Vai 4`  
  `eval/                   # clip test có nhãn + script đo accuracy`  
  `infra/                  # docker-compose.yml, k8s/`

### **Hai lưu ý trước khi bắt đầu**

> 1. GPU của Mac không dùng được từ trong container Docker hay k3d, vì container chạy trong máy ảo Linux. Vì vậy service vision chạy trực tiếp trên macOS và nói chuyện với Redpanda; k3d chỉ chứa backend, dashboard và các worker nhẹ. Phần demo autoscale dùng các worker nhẹ đó.  
> 2. Wi-Fi ở hackathon thường chặn các thiết bị nói chuyện với nhau. Nếu điện thoại không stream được sang Mac, bật hotspot từ một điện thoại và cho Mac cùng hai điện thoại camera vào chung.

### **Việc đầu tiên của từng vai**

**Vai 1, nhận diện người (Thành viên 2\)**

> 1. Đọc stream từ Z Flip, chạy SCRFD \+ ArcFace, đăng ký gallery cho 4 người trong team.  
> 2. Gắn BoT-SORT, gộp embedding theo từng track, publish person.seen.  
> 3. Khi luồng chính đã chạy: thêm AdaFace, điểm chất lượng MagFace, ngưỡng conformal.

**Vai 2, nhận diện món đồ (Thành viên 3\)**

> 1. Đọc stream từ điện thoại thứ hai; phát hiện cửa mở bằng độ sáng.  
> 2. YOLO \+ MediaPipe Hands; xác định PUT/TAKE theo hướng vật đi qua một vạch ở cửa tủ; publish item.event.  
> 3. Thêm DINOv2 \+ Hungarian để phân biệt món, rồi Grounding DINO \+ SAM 2\. Research HaMeR sớm vì nó phụ thuộc nặng vào GPU NVIDIA; nếu không chạy được trên Mac thì giữ MediaPipe.

**Vai 3, backend và matching (Dang)**

> 1. Trong 30 phút đầu: tạo repo, contracts/, fake\_events.py và docker-compose (Redpanda, Postgres), rồi chia cho cả team.  
> 2. Ghép mỗi item.event với person.seen gần nhất bằng event-time window join có watermark, ghi fridge.event, dựng tồn kho từ log.  
> 3. Matching \+ cảnh báo, API \+ SSE, rồi đến MCP server.

**Vai 4, dashboard, hạ tầng và video (Thành viên 4\)**

> 1. Dashboard chạy trên dữ liệu giả từ API của vai 3\.  
> 2. Quay sớm khoảng 20–30 clip đặt và lấy đồ có ghi nhãn (ai, món gì, PUT hay TAKE) làm bộ test, và viết script đo accuracy. Đây là nguồn số liệu cho cảnh cuối video.  
> 3. Ngay khi luồng chính chạy, quay một bản video dự phòng. Sau đó chuyển Redpanda lên cluster 3 node và thử tắt một node, rồi dựng k3d \+ KEDA \+ Grafana.

## **Kịch bản video demo**

Video dài khoảng 3 phút. Phút đầu cho thấy sản phẩm chạy thật, hai phút còn lại giới thiệu thuật toán và hạ tầng cho track over-engineered.

| Thời gian | Cảnh | Trên màn hình | Ý thuyết minh |
| :---- | :---- | :---- | :---- |
| 0:00–0:15 | Mở đầu | Ai đó mở tủ, hộp cơm của mình đã biến mất | "Ai lấy hộp cơm của tôi?" rồi đọc câu định danh dự án |
| 0:15–0:45 | Đặt đồ | Người A đặt hộp sữa vào tủ; dashboard thêm món, ghi chủ là A | Mua về, đặt thẳng vào tủ, không tag, không app |
| 0:45–1:10 | Lấy nhầm | Người B lấy hộp sữa; dashboard hiện cảnh báo | Hệ thống biết B vừa lấy đồ của A |
| 1:10–1:50 | Nhận diện người | Chia màn hình: box mặt từ hai detector, track ID, điểm nhận diện; một người lạ bị đánh dấu "lạ" | Mỗi lớp sửa một lỗi: mặt nghiêng, frame mờ, người lạ |
| 1:50–2:30 | Tay \+ vật | Mask SAM 2, mesh tay HaMeR, mặt phẳng 3D ở cửa tủ; hai món giống hệt nhau vẫn được phân biệt | Vì sao cần 3D và Hungarian algorithm |
| 2:30–2:50 | Hạ tầng | Sơ đồ kiến trúc; giả lập nhiều tủ, số pod tăng lên, trace trên Grafana; tắt một broker mà hệ thống vẫn chạy | Model nặng nên cần event bus và autoscale |
| 2:50–3:05 | MCP | Hỏi Claude: "Tuần này ai lấy đồ của A nhiều nhất?" | AI khác cũng đọc được dữ liệu tủ lạnh |
| 3:05–3:15 | Kết | Bảng accuracy khi bật và tắt từng lớp | Over-engineered, nhưng mỗi lớp đều có lý do |

Các cảnh 1:10–2:50 chỉ đưa vào kỹ thuật thật sự chạy được; kỹ thuật nào bị cắt thì bỏ khỏi video. Quay từng cảnh riêng rồi ghép lại, và thuyết minh bằng tiếng Anh nếu ban giám khảo nói tiếng Anh.

## **Phần cứng**

Chỉ dùng thiết bị team đang có; Jetson đang ở Việt Nam nên không nằm trong kế hoạch.

| Thiết bị | Vai trò |
| :---- | :---- |
| Galaxy Z Flip (gập kiểu Flex mode) | Camera quay mặt người, stream video về Mac |
| Điện thoại thứ hai của team | Quay món đồ và tay ở khu vực kệ tủ |
| Mac | Chạy inference, backend và web dashboard |

## **Ngoài phạm vi**

Những thứ dễ bị thêm vào giữa chừng nhưng **không làm**:

> * Theo dõi hạn sử dụng, gợi ý công thức nấu ăn, danh sách đi chợ  
> * App mobile riêng cho người dùng (chỉ có web dashboard)  
> * Phạt tiền, thanh toán, hoặc gửi thông báo qua SMS/email  
> * Nhiều tủ lạnh, nhiều camera cùng lúc  
> * Deploy lên cloud; demo chạy local trên Mac  
> * Tự train model từ đầu; dùng model có sẵn rồi ghép và tinh chỉnh

Quy tắc: ý tưởng mới ghi vào đây trước. Chỉ đưa vào phạm vi khi luồng chính (một người, một món, đặt vào rồi lấy ra) đã chạy trọn vẹn.

## **Quyết định**

Hackathon kết thúc lúc 13:00 ngày 8/11/2026 và nộp bằng video demo, không có phần pitch.

| Câu hỏi | Quyết định |
| :---- | :---- |
| Nhận diện món đồ | Vision thuần, không QR hay sticker: người dùng mua đồ về và đặt thẳng vào tủ |
| Camera | Hai điện thoại của team: Galaxy Z Flip quay mặt người, một điện thoại khác quay món đồ và tay |
| Phát hiện cửa mở | Đề xuất, chờ chốt: không dùng IMU; camera món đồ tự phát hiện khi đèn trong tủ bật |
| Liveness (chống giơ ảnh) | Đề xuất, chờ chốt: ngoài bản demo, chỉ làm nếu còn thời gian |
| Body re-ID | Không làm |
| Watermark join | Làm: hai camera lệch dữ liệu là vấn đề thật |
| Shadow deployment | Không làm: số accuracy lấy từ script đo trên bộ clip test của vai 4 |
| Cluster Redpanda 3 node \+ chaos test | Làm, sau khi luồng chính đã chạy với 1 node |
| Team | 4 người, ai cũng code được mọi phần; vai theo phần Chia việc |
| Sản phẩm nộp | Video demo |

