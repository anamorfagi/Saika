# -*- coding: utf-8 -*-
import io, sys
sys.path.insert(0, r"C:\AI\Saika\build\ANAMORF-0.2.1\app")
OUT = r"E:\Loading\_atlas_tmp\ru_test.txt"
from anamorf import hearing as H
tests = ["Cow","Moo","Horse","Neigh, whinny","Frog","Croak","Cricket",
         "Mosquito","Bee, wasp, etc.","Crow","Caw","Owl","Chicken, rooster",
         "Crowing, cock-a-doodle-doo","Duck","Quack","Rustling leaves",
         "Thunderstorm","Waves, surf","Vacuum cleaner","Washing machine",
         "Car alarm","Car passing by","Motorcycle","Helicopter",
         "Bird flight, flapping wings","Computer keyboard","Baby cry, infant cry",
         "Snoring","Keys jangling","Toilet flush","Chainsaw","Tick-tock"]
with io.open(OUT,"w",encoding="utf-8") as f:
    for t in tests:
        f.write("%-34s -> %s\n" % (t, H._ru(t)))
