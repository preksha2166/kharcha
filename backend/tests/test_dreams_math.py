"""Dreams math: room per week, bills first, priorities, ready dates."""

from datetime import date, timedelta

from app.finance.dreams import DreamSpec, Room, needed_per_week, next_save_day, plan_dreams, room_per_week, save_days_until

MON = date(2026, 11, 16)  # a Monday
SAT = date(2026, 11, 14)


def test_save_days_are_mondays():
    assert next_save_day(MON) == MON
    assert next_save_day(SAT) == MON
    assert save_days_until(SAT, MON + timedelta(days=14)) == 3
    assert save_days_until(SAT, SAT) == 0


def test_room_is_the_tightest_week_in_whole_dollars():
    # $1,000 now and flat: 4 Mondays in 28 days -> at most $250 a week.
    assert room_per_week(today=MON, closings=[1000.0] * 28, saved_total=0).per_week == 250
    # Rent of $900 on day 10 leaves $100 for 2 Mondays (days 0 and 7) -> $50 a week.
    closings = [1000.0] * 10 + [100.0] * 4
    assert room_per_week(today=MON, closings=closings, saved_total=0).per_week == 50
    # Money already saved for dreams isn't spare.
    assert room_per_week(today=MON, closings=[1000.0] * 28, saved_total=200).per_week == 200


def test_bills_first_short_bill_means_no_room():
    room = room_per_week(today=MON, closings=[5000.0] * 28, saved_total=0, short_bill="Spring term fee is $1,400 short")
    assert room == Room(0.0, "Spring term fee is $1,400 short")


def test_bills_may_need_dream_savings():
    room = room_per_week(today=MON, closings=[500.0] * 5 + [300.0] * 5, saved_total=400)
    assert room.per_week == 0 and "$100 of your dream savings" in room.blocked_by
    # No savings and no spare money: no room, but nothing is at risk either.
    assert room_per_week(today=MON, closings=[-10.0] * 7, saved_total=0) == Room(0.0, None)


def test_loan_reserve_lowers_room_but_doesnt_put_savings_at_risk():
    # Cash stays above the $50 saved, but the $5/day loan reserve eats the rest in the first week.
    room = room_per_week(today=MON, closings=[80.0] * 10 + [500.0] * 30, saved_total=50, reserve_per_day=5,
                         weekly_surplus=60)
    assert room.blocked_by is None and room.per_week == 0
    assert room.later_per_week == 60 and room.later_from == MON + timedelta(weeks=2)


def test_tight_stretch_then_normal_surplus():
    # A big fee on day 20 leaves $30 for 3 Mondays now (pay arrives the next day); after that the
    # normal $48 a week applies.
    closings = [1000.0] * 20 + [30.0] + [1000.0] * 9
    room = room_per_week(today=MON, closings=closings, saved_total=0, weekly_surplus=48.9)
    assert room.per_week == 10 and room.later_per_week == 48
    assert room.tight_until == MON + timedelta(days=20) and room.later_from == MON + timedelta(weeks=3)
    flight = DreamSpec(1, "Flight", 500, 0, None, 1)
    plan = plan_dreams([flight], room, MON)[0]
    assert plan.per_week == 5 and plan.later_per_week == 24 and plan.status == "saving"
    # $5 x 3 weeks, then $24 a week: 15 + 24 * 21 = 519 >= 500 -> ready on the 24th Monday.
    assert plan.ready_on == MON + timedelta(weeks=23)


def test_dated_dream_gets_what_it_needs_most_important_first():
    flight = DreamSpec(1, "Flight home", 1200, 0, MON + timedelta(weeks=26), priority=1)  # 27 Mondays
    laptop = DreamSpec(2, "Laptop", 1000, 0, MON + timedelta(weeks=14), priority=2)  # 15 Mondays
    plans = plan_dreams([laptop, flight], Room(80, None), MON)
    assert [p.id for p in plans] == [1, 2]
    f, lap = plans
    assert f.needed_per_week == needed_per_week(MON, 1200, flight.target_date) == 45
    assert f.per_week == 45 and f.status == "on_track" and f.ready_on <= flight.target_date
    assert lap.needed_per_week == 67 and lap.per_week == 35 and lap.status == "behind"
    assert lap.ready_on > laptop.target_date and "Needs $67 a week" in lap.reason


def test_undated_dream_takes_half_of_whats_left():
    plans = plan_dreams([DreamSpec(1, "Laptop", 1000, 0, None, 1)], Room(80, None), MON)
    assert plans[0].per_week == 40 and plans[0].status == "saving"
    assert plans[0].ready_on == MON + timedelta(weeks=24)  # 25 Mondays of $40


def test_waiting_paused_and_reached():
    dreams = [DreamSpec(1, "Flight", 1200, 1200, None, 1), DreamSpec(2, "Laptop", 1000, 100, None, 2, paused=True),
              DreamSpec(3, "Guitar", 300, 0, None, 3)]
    plans = plan_dreams(dreams, Room(0, "Spring term fee is $1,400 short"), MON)
    assert [p.status for p in plans] == ["reached", "paused", "waiting_for_bills"]
    assert plans[1].percent == 10.0
    assert plans[2].reason.startswith("Bills first: Spring term fee")


def test_last_week_only_takes_whats_left():
    plans = plan_dreams([DreamSpec(1, "Shoes", 100, 90, None, 1)], Room(80, None), MON)
    assert plans[0].per_week == 10 and plans[0].ready_on == MON
