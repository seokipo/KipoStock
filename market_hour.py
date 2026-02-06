import datetime

class MarketHour:
	"""장 시간 관련 상수 및 메서드를 관리하는 클래스"""
	
	# 장 시작/종료 시간 상수
	MARKET_START_HOUR = 9
	MARKET_START_MINUTE = 0
	MARKET_END_HOUR = 15
	MARKET_END_MINUTE = 30
	
	@classmethod
	def set_market_hours(cls, start_hour, start_minute, end_hour, end_minute):
		"""장 시작/종료 시간을 설정합니다."""
		cls.MARKET_START_HOUR = int(start_hour)
		cls.MARKET_START_MINUTE = int(start_minute)
		cls.MARKET_END_HOUR = int(end_hour)
		cls.MARKET_END_MINUTE = int(end_minute)

	
	@staticmethod
	def _is_weekday():
		"""평일인지 확인합니다."""
		return datetime.datetime.now().weekday() < 5
	
	@staticmethod
	def _get_market_time(hour, minute):
		"""장 시간을 반환합니다."""
		now = datetime.datetime.now()
		return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
	
	@staticmethod
	def is_holiday():
		"""증시 휴장일인지 확인합니다 (2025-2026 주요 휴장일)"""
		now = datetime.datetime.now()
		today_str = now.strftime('%Y-%m-%d')
		
		# 2025~2026 주요 증시 휴장일 (토/일 제외)
		holidays = [
			"2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30", # 신정, 설날
			"2025-03-03", "2025-05-01", "2025-05-05", "2025-05-06", # 삼일절대체, 근로자, 어린이, 석탄신일
			"2025-06-06", "2025-08-15", "2025-10-03", "2025-10-06", # 현충일, 광복절, 개천절, 추석
			"2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25", # 추석연휴, 한글날, 성탄절
			"2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", # 신정, 설날
			"2026-03-02", "2026-05-01", "2026-05-05", "2026-05-25", # 삼일절대체, 근로자, 어린이, 석탄신일
			"2026-06-06", "2026-08-14", "2026-08-15", "2026-09-24", # 현충일, 광복절대체, 추석
			"2026-09-25", "2026-09-26", "2026-10-03", "2026-10-09", # 추석연휴, 개천절, 한글날
			"2026-12-25"                                            # 성탄절
		]
		return today_str in holidays

	@classmethod
	def is_market_open_time(cls):
		"""현재 시간이 장 시간인지 확인합니다."""
		if not cls._is_weekday() or cls.is_holiday():
			return False
		now = datetime.datetime.now()
		market_open = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		market_close = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		return market_open <= now <= market_close

	@classmethod
	def is_pre_market_reservation_time(cls):
		"""장 시작 전 예약 가능 시간(평일 08:00 ~ 설정된 시작 시간)인지 확인합니다."""
		if not cls._is_weekday() or cls.is_holiday():
			return False
		now = datetime.datetime.now()
		now_val = now.hour * 100 + now.minute
		market_start = cls.MARKET_START_HOUR * 100 + cls.MARKET_START_MINUTE
		return 800 <= now_val < market_start
	
	@classmethod
	def is_market_start_time(cls):
		"""현재 시간이 장 시작 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_start = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		return now >= market_start and (now - market_start).seconds < 60  # 1분 이내
	
	@classmethod
	def is_market_end_time(cls):
		"""현재 시간이 장 종료 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_end = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		return now >= market_end and (now - market_end).seconds < 60  # 1분 이내

	@classmethod
	def is_waiting_period(cls):
		"""장 종료 시간 ~ 익일 오전 9:00 사이인지 확인합니다."""
		now = datetime.datetime.now()
		now_time = now.hour * 100 + now.minute
		
		market_end_time = cls.MARKET_END_HOUR * 100 + cls.MARKET_END_MINUTE
		market_start_time = cls.MARKET_START_HOUR * 100 + cls.MARKET_START_MINUTE
		
		# 설정된 종료 시간 이후거나 설정된 시작 시간 이전이면 True
		if now_time >= market_end_time or now_time < market_start_time:
			return True
		return False

	@staticmethod
	def is_actual_market_open_time():
		"""사용자 설정과 관계없이 실제 한국 거래소 데이터 발생 시간(08:30~15:40)인지 확인합니다."""
		now = datetime.datetime.now()
		if now.weekday() >= 5: # 주말 제외
			return False
		now_val = now.hour * 100 + now.minute
		# [수정] 장후 시간외 거래(15:30~15:40)까지 커버하기 위해 1540으로 연장
		return 830 <= now_val < 1540

	# [신규] 수동 시작 오버라이드 플래그
	_MANUAL_OVERRIDE = False

	@classmethod
	def set_manual_mode(cls, enabled: bool):
		"""수동 시작 모드 활성화/비활성화 (설정 시간 무시)"""
		cls._MANUAL_OVERRIDE = enabled
		if enabled:
			print("🕐 [MarketHour] 수동 모드 활성화: 설정된 시작/종료 시간을 무시합니다.")
		else:
			print("🕐 [MarketHour] 수동 모드 해제: 설정된 시간을 준수합니다.")

	@classmethod
	def is_waiting_period(cls):
		"""장 종료 시간 ~ 익일 오전 9:00 사이인지 확인합니다."""
		
		# [수정] 수동 모드일 경우: 실제 장 운영 시간이면 대기 시간이 아님 (무조건 통과)
		if cls._MANUAL_OVERRIDE:
			if cls.is_actual_market_open_time():
				return False # 장중이면 대기 아님 -> 매매 진행
			# 수동 모드라도 장 시간이 아니면(밤 등) 대기
		
		now = datetime.datetime.now()
		now_time = now.hour * 100 + now.minute
		
		market_end_time = cls.MARKET_END_HOUR * 100 + cls.MARKET_END_MINUTE
		market_start_time = cls.MARKET_START_HOUR * 100 + cls.MARKET_START_MINUTE
		
		# 설정된 종료 시간 이후거나 설정된 시작 시간 이전이면 True
		if now_time >= market_end_time or now_time < market_start_time:
			return True
		return False
