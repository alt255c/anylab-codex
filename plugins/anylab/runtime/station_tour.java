class Режиссёр implements Runnable {
    final boolean trial = PILOT_MODE;
    final double[] v = {1130, 950, 540, 39, -138};
    final double[] velocity = {0,0,0,0,0};
    final double[] limits = {125,125,110,12,22};
    final double[] accelerations = {205,205,165,30,48};
    final double[] viewSent = {1130,950,540,39,-138};
    final double[] followOffset = new double[3];
    final double[] targetOffset = new double[3];
    final double[] viewed = {790,645,8};
    Object cameraSubject;
    double start = -1, wallStart, stageStart, nextArrival;
    long lastClock=0;
    double cameraDt=.033333;
    int scene, sent;
    boolean is3D;
    boolean introDiagram;
    String label = "";

    double smooth(double value) {
        double u = Math.max(0, Math.min(1, value));
        return u*u*(3-2*u);
    }
    void phase(String name) {
        if (name.equals(label)) return;
        label = name;
        try {
            String row = name + ";" + (time()-start) + ";" +
              (System.nanoTime()/1e9-wallStart) + ";" + arrived + ";" +
              served + ";" + paid + ";" + returnedDrivers + ";" +
              завершилиОбъезд + ";" + резервуарАИ92.amount(CUBIC_METER) + "\n";
            java.nio.file.Files.writeString(java.nio.file.Path.of(TRACE_PATH), row,
              java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch(java.io.IOException e) { throw new RuntimeException(e); }
    }
    void view(boolean three) {
        if (is3D == three) return;
        is3D = three;
        if (!trial) navigate(three ? view3D : view2D);
    }
    void glide(double[] pos,double[] speed,int i,double dest,double top,double accel) {
        final double dt=cameraDt;
        double delta=dest-pos[i];
        double target=Math.copySign(Math.min(top,Math.min(Math.abs(delta)*.75,Math.sqrt(2*accel*Math.abs(delta)))),delta);
        double change=Math.max(-accel*dt,Math.min(accel*dt,target-speed[i]));
        speed[i]+=change;
        pos[i]+=speed[i]*dt;
    }
    void plan(double x,double y,double width) {
        if (trial) return;
        view2D.setX(x);view2D.setY(y);view2D.setWidth(width);view2D.setHeight(960);
        view2D.navigateTo();
        groupMainMenu.setPos(x,y);
    }
    void move(double x,double y,double z,double pitch,double yaw) {
        if(trial) return;
        cameraSubject=null;
        double length=(v[2]-8)/Math.tan(Math.toRadians(v[3]));
        viewed[0]=v[0]+length*Math.cos(Math.toRadians(v[4]));
        viewed[1]=v[1]+length*Math.sin(Math.toRadians(v[4]));
        viewed[2]=8;
        double heading=v[4]+(((yaw-v[4]+540)%360)-180);
        double[] point={x,y,z,pitch,heading};
        for(int i=0;i<5;i++)glide(v,velocity,i,point[i],limits[i],accelerations[i]);
        publishCamera(false);
    }
    void publishCamera(boolean following) {
        double positionStep=following ? .001 : .28, angleStep=following ? .001 : .035;
        if(Math.abs(v[0]-viewSent[0])<positionStep && Math.abs(v[1]-viewSent[1])<positionStep &&
           Math.abs(v[2]-viewSent[2])<positionStep && Math.abs(v[3]-viewSent[3])<angleStep && Math.abs(v[4]-viewSent[4])<angleStep) return;
        System.arraycopy(v,0,viewSent,0,v.length);
        camera.setPos(v[0],v[1],v[2]);
        camera.setRotationX(Math.toRadians(v[3]));camera.setRotationZ(Math.toRadians(v[4]));
        camera.update();
    }
    void follow(Car c) {
        double x=c.getX(), y=c.getY();
        double east=smooth((900-x)/148), roof=east*smooth((x-403)/30);
        aim(c,x,y,8,151-98*east,126-50*east,116-83*roof);
    }
    void followDriver(Driver driver) {
        aim(driver,driver.getX(),driver.getY(),11,62,74,40);
    }
    void aim(Object subject,double x,double y,double height,double dx,double dy,double cameraHeight) {
        if(trial) return;
        double[] position={x+dx,y+dy,cameraHeight};
        double[] target={x,y,height};
        if(cameraSubject!=subject) {
            cameraSubject=subject;
            for(int i=0;i<3;i++) {
                followOffset[i]=v[i]-position[i];
                targetOffset[i]=viewed[i]-target[i];
            }
        }
        for(int i=0;i<3;i++) {
            followOffset[i]*=Math.exp(-cameraDt*4.8);
            targetOffset[i]*=Math.exp(-cameraDt*9.0);
            v[i]=position[i]+followOffset[i];
            viewed[i]=target[i]+targetOffset[i];
        }
        double tx=viewed[0]-v[0],ty=viewed[1]-v[1];
        v[3]=Math.toDegrees(Math.atan2(v[2]-viewed[2],Math.hypot(tx,ty)));
        v[4]=Math.toDegrees(Math.atan2(ty,tx));
        java.util.Arrays.fill(velocity,0);
        publishCamera(true);
    }
    boolean fueling(Car car) {
        return car!=null && fuelDispensers.stream().anyMatch(pump -> pump.carBeingFueled==car);
    }
    void overview() { move(1120,920,510,39,-138); }
    void stage(int newScene) { scene=newScene; stageStart=time(); }

    @Override public void run() {
        if(!trial) {
            if(!getEngine().getRealTimeMode()) getEngine().setRealTimeMode(true);
            if(Math.abs(getEngine().getRealTimeScale()-TOUR_SPEED)>1e-9) getEngine().setRealTimeScale(TOUR_SPEED);
            long clock=System.nanoTime();
            if(lastClock!=0)cameraDt=Math.min(.046,Math.max(.0,(clock-lastClock)/1e9));
            lastClock=clock;
        }
        if(start<0) {
            if(!trial && !java.nio.file.Files.exists(java.nio.file.Path.of(START_PATH))) return;
            wallStart=System.nanoTime()/1e9;
            start=time();
            stage(0);
            plan(-75,-25,1460);
            phase("начало");
        }
        double elapsed=time()-stageStart;
        if(scene==0) {
            строкаКадра="Заезд на АЗС";
            view(false);
            if(!trial) {
                double intro=System.nanoTime()/1e9-wallStart;
                if(intro>=4 && !introDiagram) { anylabBlockDiagram.navigateTo(); introDiagram=true; }
                if(intro<8) return;
                plan(-75,-25,1460);
            }
            if(elapsed>2.4) { прибытиеАвтомобилей.inject(1);stage(1);phase("подача первой машины"); }
        } else if(scene==1) {
            Car subject=кадрМашина;
            Driver person=кадрВодитель;
            boolean in3D=elapsed>=8;
            view(in3D);
            if (!in3D) move(1110,840,290,35,-138);
            if(person==null && subject!=null && !геройВыехал) {
                if(in3D) follow(subject);
            }
            строкаКадра="Автомобиль едет к колонке";
            if(!геройВыехал && fueling(subject)) {
                phase("заправка автомобиля");строкаКадра="Заправка автомобиля";
            }
            if(person!=null) {
                followDriver(person);
                if(геройОплатил) {phase("обратно к автомобилю");строкаКадра="Водитель возвращается к своей машине";}
                else if(person.getX()<370) {phase("у кассы");строкаКадра="Оплата в павильоне";}
                else {phase("выход водителя");строкаКадра="Водитель идёт к кассе";}
            } else if(геройВернулся) {
                phase("водитель вернулся");строкаКадра="Водитель сел в машину и выезжает";
            }
            if(геройВыехал) { phase("первая машина выехала");stage(2); nextArrival=time()+2; }
        } else if(scene==2) {
            if(elapsed<1.5) {
                overview();
                строкаКадра="Первый автомобиль покинул АЗС";
            } else {
                view(true);
                Car focus=кадрФон;
                if(focus!=null) follow(focus);
                else overview();
                if (fueling(focus)) {
                    phase("другой автомобиль заправляется");
                    строкаКадра="Заправка автомобиля у колонки";
                } else {
                    phase("движение других автомобилей");
                    строкаКадра="Движение автомобилей на территории АЗС";
                }
            }
            if(time()>=nextArrival && sent<2) {
                прибытиеАвтомобилей.inject(1);sent++;nextArrival=time()+10;
            }
            if(кадрВыездНачался) {
                phase("другой автомобиль выезжает");
                stage(3);
            }
        } else if(scene==3) {
            строкаКадра="Автомобиль выезжает с АЗС";
            if(кадрВыездЗакончен) {phase("автомобиль выехал с АЗС");stage(5);}
            else follow(кадрВыезд);
        } else if(scene==5) {
            if(elapsed>1.2) {
                топливоСлива=GAS92; бензовозВРаботе=true;
                бензовозТекущий=new GasolineTanker(GAS92,30);
                приёмБензовоза.take(бензовозТекущий);
                stage(6);
                view(false);
                plan(10,175,860);
                phase("въезд бензовоза");
            }
        } else if(scene==6) {
            double amount=резервуарАИ92.amount(CUBIC_METER);
            double portion=времяПервогоСлива<0 ? 0 : Math.max(0,(amount-последнийУровеньДо)/(30-последнийУровеньДо));
            boolean tank3D=portion>=0.5 || полныеПополнения>0;
            GasolineTanker tanker=бензовозТекущий;
            view(tank3D);
            if(tanker!=null) aim(tanker,tanker.getX()+14,tanker.getY()+4,9,43,101,67);
            else overview();
            String subtitle=идётСлив ? (tank3D?"Слив бензовоза · 3D":"Слив бензовоза · 2D") :
                полныеПополнения>0 ? "Резервуар заполнен" : времяПервогоСлива>=0 ? "Слив завершён, бензовоз выезжает" : "Бензовоз на подъезде";
            строкаКадра=String.format(java.util.Locale.forLanguageTag("ru"),"%s   |   АИ-92: %.2f / 30 м³",subtitle,amount);
            if(идётСлив) phase(tank3D?"слив 3D — половина объёма":"слив 2D — начало");
            if(полныеПополнения>0) {
                phase("резервуар заполнен, бензовоз выехал");
                stage(7);
            }
        } else if(scene==7) {
            overview();строкаКадра="Автозаправочная станция";
            if(elapsed>6) {
                stage(8);phase("конец");
                try { java.nio.file.Files.writeString(java.nio.file.Path.of(FINISH_PATH), "done"); }
                catch(java.io.IOException e) { throw new RuntimeException(e); }
            }
        }
    }
}
camera.setPos(1130,950,540);
camera.setRotationX(Math.toRadians(39));camera.setRotationZ(Math.toRadians(-138));camera.update();
navigate(view2D);
режиссёрКадра=new Режиссёр();
