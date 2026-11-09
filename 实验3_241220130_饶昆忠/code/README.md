# 校园二手交易系统：实验三代码

本目录是实验二 UML 设计的可运行后端实现。使用 Python 3.11+ 标准库与 SQLite，不需要安装第三方包。服务端以 JSON HTTP API 提供功能，未制作图形界面；手册允许无 GUI 实现。

## 对应实验二设计

| 实验二模块 / 图 | 本项目代码 |
|---|---|
| 账号与鉴权 | `campus_market/accounts.py`、`security.py` |
| 商品状态图、商品审核 | `campus_market/listings.py` |
| 预约状态图、预约时序图 | `campus_market/reservations.py`、`base.py` |
| 举报处理 | `campus_market/reports.py` |
| 通知、统计与日志 | `campus_market/operations.py`、`base.py` |
| 类图中的实体与唯一约束 | `campus_market/storage.py` |
| 组件图中的统一 API 入口 | `campus_market/http_api.py`、`main.py` |

`storage.py` 定义用户、商品、预约、举报、请求回执、消息及操作日志表。`BaseService.mutate` 在 `BEGIN IMMEDIATE` 事务中查重并保存首次结果；数据库的部分唯一索引再次保证同一商品最多一条有效预约。商品状态与预约状态在同一事务里变更。请求编号在同一账号所有变更操作中唯一，重发相同内容返回首次结果，不同内容返回 `request_id_conflict`。

## 本机运行

```sh
cd code
python3 --version
python3 main.py --db data/market.db --school-domain campus.edu.cn serve
```

默认监听 `127.0.0.1:8765`。本机原型的 `/auth/code` 会把六位验证码直接返回给调用方，以便不接入真实邮件服务也能演示注册。它只能用于本机实验。正式部署须换成邮件发送，关闭返回验证码，添加 HTTPS 反向代理和登录限流。

管理员只能由本机命令开通，HTTP API 没有自助开通入口：

```sh
python3 main.py --db data/market.db --school-domain campus.edu.cn \
  bootstrap-admin --email admin@campus.edu.cn
```

定时提醒与到期任务可手动执行：

```sh
python3 main.py --db data/market.db --school-domain campus.edu.cn run-jobs
```

`serve` 启动时会同时启动每分钟运行一次的定时任务，以满足到期后五分钟内处理的要求。独立执行 `run-jobs` 也可重试；消息通过 `(recipient_id, event_id)` 唯一约束去重。`--now` 参数仅用于测试模拟时间。正式多实例部署应改用单独的任务调度服务。

## HTTP API

商品、预约、举报、联系方式和消息已读的写操作都在 JSON 请求体中携带 `request_id`。注册、登录、获取验证码和登出不使用该编号。登录后在请求头中带 `Authorization: Bearer <token>`。价格输入单位为元，数据库保存整数分。

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/auth/code` | 获取本机演示验证码 |
| POST | `/auth/register` | 验证学校邮箱并注册 |
| POST | `/auth/login`、`/auth/logout` | 登录、退出 |
| GET、PUT | `/me`、`/me/contact` | 查看和修改自己的联系方式 |
| GET、POST | `/listings` | 公开搜索、创建草稿 |
| GET、PUT | `/listings/{id}` | 详情、修改商品 |
| POST | `/listings/{id}/submit`、`withdraw`、`remove`、`review` | 提交、撤回、下架、审核 |
| GET | `/me/listings`、`/admin/listings` | 个人和管理员商品列表 |
| POST | `/listings/{id}/reserve` | 发起预约 |
| GET | `/me/reservations`、`/seller/reservations` | 买家和卖家预约列表 |
| GET | `/reservations/{id}`、`/reservations/{id}/contact` | 预约详情、按现态读取对方联系方式 |
| POST | `/reservations/{id}/decide`、`cancel`、`complete` | 卖家处理、取消、买家确认完成 |
| POST | `/listings/{id}/reports` | 提交举报 |
| GET | `/me/reports`、`/admin/reports`、`/reports/{id}` | 查询举报 |
| POST | `/reports/{id}/decide` | 管理员驳回或确认违规 |
| GET | `/notifications`、`/statistics?month=YYYY-MM` | 消息与月度成交统计 |
| POST | `/notifications/{id}/read` | 标记已读 |
| GET | `/admin/audit` | 管理员查询只追加日志 |

示例注册及登录：

```sh
curl -s -X POST http://127.0.0.1:8765/auth/code \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@campus.edu.cn"}'

# 将上一步返回的 verification_code 填入下方 JSON。
curl -s -X POST http://127.0.0.1:8765/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@campus.edu.cn","code":"123456",\
       "password":"example-pass-123","contact":"站内约定的联系方式"}'

curl -s -X POST http://127.0.0.1:8765/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@campus.edu.cn","password":"example-pass-123"}'
```

商品审核操作要携带当前 `expected_version`。公开搜索支持 `keyword`、`category`、`min_price`、`max_price`、`sort=newest|price_asc|price_desc`、`limit`、`offset`。业务错误返回稳定的 `error` 字段与说明。

## 检查与规模

```sh
python3 -m compileall -q campus_market main.py
python3 -m unittest discover -s tests -v
wc -l campus_market/*.py main.py
```

当前应用源码超过 2200 行，均为手写的 Python 文件，不包含 GUI 工具自动生成代码。测试覆盖账号、权限、草稿与审核、筛选、请求重发和冲突、并发预约、联系方式、交易完成、举报合并、到期重试和 HTTP 冒烟路径。

## 范围与部署说明

这是课程实验的本机后端原型。实验二的 11 张 Figma 界面尚未接入本 API。真实学校邮箱域名仍需配置；默认 `example.edu.cn` 只是占位。图片使用 HTTPS URL，不包含上传存储服务。性能指标、10 名学生易用性与正式 HTTPS 部署尚未做实测，因此不能把本机测试结果写成这些指标已达标。SQLite 足以演示事务与唯一约束；多实例部署时应重新评估数据库、任务调度和消息投递。代码仅实现本地 Git 可管理文件，远程仓库展示和实验报告需在后续完成。
