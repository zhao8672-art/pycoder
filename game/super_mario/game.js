// ==================== 超级玛丽游戏引擎 ====================
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');

const CANVAS_WIDTH = 800;
const CANVAS_HEIGHT = 500;
canvas.width = CANVAS_WIDTH;
canvas.height = CANVAS_HEIGHT;

let gameState = 'start';
let score = 0;
let coins = 0;
let lives = 3;
let timer = 300;
let timerInterval = null;
let cameraX = 0;

const GRAVITY = 0.6;
const FRICTION = 0.8;
const keys = {};

class Sprite {
    constructor(x, y, width, height, color) {
        this.x = x; this.y = y;
        this.width = width; this.height = height;
        this.color = color;
        this.vx = 0; this.vy = 0;
        this.grounded = false; this.dead = false;
    }
    draw(ctx, camX) {
        ctx.fillStyle = this.color;
        ctx.fillRect(this.x - camX, this.y, this.width, this.height);
    }
    update() {
        this.vy += GRAVITY;
        this.x += this.vx;
        this.y += this.vy;
        this.vx *= FRICTION;
    }
    getBounds() { return {x:this.x, y:this.y, w:this.width, h:this.height}; }
    collidesWith(other) {
        const a = this.getBounds(), b = other.getBounds();
        return a.x < b.x+b.w && a.x+a.w > b.x && a.y < b.y+b.h && a.y+a.h > b.y;
    }
}

class Mario extends Sprite {
    constructor(x, y) {
        super(x, y, 32, 40, '#e52521');
        this.speed = 5; this.jumpPower = -13;
        this.facing = 1; this.invincible = 0;
        this.animFrame = 0; this.animTimer = 0;
    }
    update(platforms, enemies, coinItems, pipeList, flagPole) {
        if (this.dead) return;
        if (this.invincible > 0) this.invincible--;
        this.animTimer++;
        if (this.animTimer > 8) { this.animTimer = 0; this.animFrame = (this.animFrame+1)%3; }
        if (keys['ArrowLeft']||keys['a']) { this.vx -= 1; this.facing = -1; if(this.vx<-this.speed)this.vx=-this.speed; }
        if (keys['ArrowRight']||keys['d']) { this.vx += 1; this.facing = 1; if(this.vx>this.speed)this.vx=this.speed; }
        if ((keys['ArrowUp']||keys[' ']||keys['w']) && this.grounded) { this.vy = this.jumpPower; this.grounded = false; }
        this.vy += GRAVITY; this.x += this.vx; this.y += this.vy; this.vx *= FRICTION;
        if (this.x < 0) this.x = 0;
        this.grounded = false;
        for (const plat of [...platforms,...pipeList]) {
            if (this.collidesWith(plat)) {
                const ox = Math.min(this.x+this.width-plat.x, plat.x+plat.width-this.x);
                const oy = Math.min(this.y+this.height-plat.y, plat.y+plat.height-this.y);
                if (oy < ox) {
                    if (this.y+this.height/2 < plat.y+plat.height/2) { this.y=plat.y-this.height; this.vy=0; this.grounded=true; }
                    else { this.y=plat.y+plat.height; this.vy=0; }
                } else {
                    if (this.x+this.width/2 < plat.x+plat.width/2) this.x=plat.x-this.width;
                    else this.x=plat.x+plat.width;
                    this.vx = 0;
                }
            }
        }
        if (this.y > CANVAS_HEIGHT+100) this.die();
        for (let i=coinItems.length-1; i>=0; i--) {
            if (!coinItems[i].collected && this.collidesWith(coinItems[i])) {
                coinItems[i].collected = true; coins++; score+=100; updateUI();
            }
        }
        for (const enemy of enemies) {
            if (enemy.dead) continue;
            if (this.collidesWith(enemy)) {
                if (this.vy>0 && this.y+this.height-enemy.y < 20) { enemy.die(); this.vy=-8; score+=200; updateUI(); }
                else if (this.invincible<=0) this.takeDamage();
            }
        }
        if (flagPole && this.x+this.width >= flagPole.x) winGame();
    }
    takeDamage() { if(this.invincible>0)return; lives--; this.invincible=90; updateUI(); if(lives<=0)this.die(); }
    die() { this.dead=true; gameOver(); }
    draw(ctx, camX) {
        if (this.dead) return;
        if (this.invincible>0 && Math.floor(this.invincible/4)%2===0) return;
        const x=this.x-camX, y=this.y;
        ctx.fillStyle='#e52521'; ctx.fillRect(x+4,y+12,24,20);
        ctx.fillStyle='#fbb'; ctx.fillRect(x+6,y,20,14);
        ctx.fillStyle='#e52521'; ctx.fillRect(x+4,y-2,24,6);
        ctx.fillStyle='#000';
        if(this.facing===1){ctx.fillRect(x+18,y+4,3,3);ctx.fillRect(x+16,y+9,8,2);}
        else{ctx.fillRect(x+10,y+4,3,3);ctx.fillRect(x+8,y+9,8,2);}
        ctx.fillStyle='#0051c8'; ctx.fillRect(x+4,y+26,24,10);
        ctx.fillStyle='#0051c8';
        if(!this.grounded){ctx.fillRect(x+2,y+34,10,6);ctx.fillRect(x+20,y+30,10,6);}
        else if(Math.abs(this.vx)>0.5){const lo=this.animFrame===1?4:0;ctx.fillRect(x+4-lo,y+34,10,6);ctx.fillRect(x+18+lo,y+34,10,6);}
        else{ctx.fillRect(x+4,y+34,10,6);ctx.fillRect(x+18,y+34,10,6);}
        ctx.fillStyle='#fff';
        if(this.facing===1)ctx.fillRect(x+26,y+16,6,6);else ctx.fillRect(x,y+16,6,6);
    }
}

class Goomba extends Sprite {
    constructor(x, y, patrolDist) {
        super(x, y, 30, 30, '#8b4513');
        this.startX=x; this.patrolDist=patrolDist||100;
        this.vx=-1.5; this.alive=true; this.squishTimer=0;
    }
    update(platforms) {
        if(!this.alive){this.squishTimer--;return this.squishTimer>0;}
        this.vy+=GRAVITY; this.x+=this.vx; this.y+=this.vy;
        this.grounded=false;
        for(const plat of platforms){
            if(this.collidesWith(plat)){
                const oy=Math.min(this.y+this.height-plat.y,plat.y+plat.height-this.y);
                const ox=Math.min(this.x+this.width-plat.x,plat.x+plat.width-this.x);
                if(oy<ox){
                    if(this.y+this.height/2<plat.y+plat.height/2){this.y=plat.y-this.height;this.vy=0;this.grounded=true;}
                    else{this.y=plat.y+plat.height;this.vy=0;}
                }else{this.vx=-this.vx;if(this.x<this.startX-this.patrolDist||this.x>this.startX+this.patrolDist)this.vx=-this.vx;if(this.x<this.startX-this.patrolDist)this.x=this.startX-this.patrolDist;if(this.x>this.startX+this.patrolDist)this.x=this.startX+this.patrolDist;}
            }
        }
        if(this.y>CANVAS_HEIGHT+100)return false; return true;
    }
    die(){this.alive=false;this.squishTimer=20;this.height=10;this.y+=20;}
    draw(ctx,camX){
        if(this.squishTimer!==undefined&&this.squishTimer<=0)return;
        const x=this.x-camX,y=this.y;
        if(!this.alive){ctx.fillStyle='#8b4513';ctx.fillRect(x,y,30,10);return;}
        ctx.fillStyle='#8b4513';ctx.fillRect(x+2,y+4,26,22);
        ctx.fillStyle='#a0522d';ctx.fillRect(x,y,30,16);
        ctx.fillStyle='#fff';ctx.fillRect(x+5,y+4,7,7);ctx.fillRect(x+18,y+4,7,7);
        ctx.fillStyle='#000';ctx.fillRect(x+8,y+6,3,4);ctx.fillRect(x+20,y+6,3,4);
        ctx.fillStyle='#000';ctx.fillRect(x+4,y+2,10,2);ctx.fillRect(x+16,y+2,10,2);
        ctx.fillStyle='#000';const fo=Math.sin(Date.now()/100)*3;ctx.fillRect(x+2+fo,y+24,10,6);ctx.fillRect(x+18-fo,y+24,10,6);
    }
}

class CoinItem extends Sprite {
    constructor(x,y){super(x,y,20,20,'#ffd700');this.collected=false;this.bobOffset=Math.random()*Math.PI*2;}
    draw(ctx,camX){
        if(this.collected)return;
        const bobY=Math.sin(Date.now()/300+this.bobOffset)*4;
        const x=this.x-camX,y=this.y+bobY;
        ctx.fillStyle='#ffd700';ctx.beginPath();ctx.arc(x+10,y+10,10,0,Math.PI*2);ctx.fill();
        ctx.fillStyle='#ffaa00';ctx.beginPath();ctx.arc(x+10,y+10,7,0,Math.PI*2);ctx.fill();
        ctx.fillStyle='#ffd700';ctx.font='bold 12px Arial';ctx.textAlign='center';ctx.fillText('$',x+10,y+14);
    }
}

class Pipe extends Sprite {
    constructor(x,y,w,h){super(x,y,w,h,'#00aa00');this.topHeight=20;}
    draw(ctx,camX){
        const x=this.x-camX;
        ctx.fillStyle='#00cc00';ctx.fillRect(x+4,this.y+this.topHeight,this.width-8,this.height-this.topHeight);
        ctx.fillStyle='#00ee00';ctx.fillRect(x,this.y,this.width,this.topHeight);
        ctx.fillStyle='#66ff66';ctx.fillRect(x+6,this.y+this.topHeight,4,this.height-this.topHeight);
        ctx.fillRect(x+2,this.y+2,4,this.topHeight-4);
        ctx.strokeStyle='#006600';ctx.lineWidth=2;ctx.strokeRect(x,this.y,this.width,this.topHeight);ctx.strokeRect(x+4,this.y+this.topHeight,this.width-8,this.height-this.topHeight);
    }
}

let mario, platforms=[], enemies=[], coinItems=[], pipes=[], flagPole=null;
let clouds=[], bushes=[], hills=[];

function createLevel(){
    platforms=[];enemies=[];coinItems=[];pipes=[];clouds=[];bushes=[];hills=[];
    for(let i=0;i<20;i++)platforms.push(new Sprite(i*40,CANVAS_HEIGHT-40,40,40,'#c84c0c'));
    for(let i=22;i<40;i++)platforms.push(new Sprite(i*40,CANVAS_HEIGHT-40,40,40,'#c84c0c'));
    for(let i=42;i<60;i++)platforms.push(new Sprite(i*40,CANVAS_HEIGHT-40,40,40,'#c84c0c'));
    for(let i=62;i<85;i++)platforms.push(new Sprite(i*40,CANVAS_HEIGHT-40,40,40,'#c84c0c'));
    const brickPositions=[{x:8,y:CANVAS_HEIGHT-140,w:4},{x:15,y:CANVAS_HEIGHT-180,w:3},{x:25,y:CANVAS_HEIGHT-140,w:5},{x:35,y:CANVAS_HEIGHT-160,w:3},{x:45,y:CANVAS_HEIGHT-140,w:4},{x:55,y:CANVAS_HEIGHT-180,w:6}];
    for(const bp of brickPositions){for(let j=0;j<bp.w;j++){const p=new Sprite(bp.x*40+j*40,bp.y,40,40,'#b86f0b');platforms.push(p);if(j===1&&bp.w>1){p.color='#ffd700';p.isQuestion=true;}}}
    pipes.push(new Pipe(12*40,CANVAS_HEIGHT-100,60,60));
    pipes.push(new Pipe(20*40,CANVAS_HEIGHT-120,60,80));
    pipes.push(new Pipe(30*40,CANVAS_HEIGHT-100,60,60));
    pipes.push(new Pipe(48*40,CANVAS_HEIGHT-120,60,80));
    enemies.push(new Goomba(10*40,CANVAS_HEIGHT-80,80));
    enemies.push(new Goomba(18*40,CANVAS_HEIGHT-80,60));
    enemies.push(new Goomba(28*40,CANVAS_HEIGHT-80,100));
    enemies.push(new Goomba(38*40,CANVAS_HEIGHT-80,80));
    enemies.push(new Goomba(46*40,CANVAS_HEIGHT-80,60));
    enemies.push(new Goomba(52*40,CANVAS_HEIGHT-80,100));
    enemies.push(new Goomba(65*40,CANVAS_HEIGHT-80,80));
    enemies.push(new Goomba(70*40,CANVAS_HEIGHT-80,60));
    const coinPositions=[{x:6,y:CANVAS_HEIGHT-200},{x:7,y:CANVAS_HEIGHT-200},{x:8,y:CANVAS_HEIGHT-200},{x:15,y:CANVAS_HEIGHT-240},{x:16,y:CANVAS_HEIGHT-240},{x:25,y:CANVAS_HEIGHT-200},{x:26,y:CANVAS_HEIGHT-200},{x:27,y:CANVAS_HEIGHT-200},{x:35,y:CANVAS_HEIGHT-220},{x:36,y:CANVAS_HEIGHT-220},{x:45,y:CANVAS_HEIGHT-200},{x:46,y:CANVAS_HEIGHT-200},{x:55,y:CANVAS_HEIGHT-240},{x:56,y:CANVAS_HEIGHT-240},{x:57,y:CANVAS_HEIGHT-240},{x:58,y:CANVAS_HEIGHT-240},{x:21,y:CANVAS_HEIGHT-100},{x:22,y:CANVAS_HEIGHT-130},{x:23,y:CANVAS_HEIGHT-100},{x:43,y:CANVAS_HEIGHT-100},{x:44,y:CANVAS_HEIGHT-130},{x:45,y:CANVAS_HEIGHT-100}];
    for(const cp of coinPositions)coinItems.push(new CoinItem(cp.x*40+10,cp.y));
    flagPole={x:80*40,y:CANVAS_HEIGHT-240,height:200};
    for(let i=0;i<30;i++)clouds.push({x:i*300+Math.random()*200,y:30+Math.random()*80,size:30+Math.random()*40});
    for(let i=0;i<25;i++)bushes.push({x:i*350+Math.random()*150,size:40+Math.random()*60});
    for(let i=0;i<15;i++)hills.push({x:i*600+Math.random()*300,size:80+Math.random()*100});
    mario=new Mario(100,CANVAS_HEIGHT-100);
}

function drawBackground(){
    const gradient=ctx.createLinearGradient(0,0,0,CANVAS_HEIGHT);
    gradient.addColorStop(0,'#5c94fc');gradient.addColorStop(1,'#87ceeb');
    ctx.fillStyle=gradient;ctx.fillRect(0,0,CANVAS_WIDTH,CANVAS_HEIGHT);
    ctx.fillStyle='#90cc90';
    for(const hill of hills){const hx=hill.x-cameraX*0.3;if(hx>-hill.size*2&&hx<CANVAS_WIDTH+hill.size*2){ctx.beginPath();ctx.arc(hx,CANVAS_HEIGHT-40,hill.size,Math.PI,0);ctx.fill();}}
    ctx.fillStyle='rgba(255,255,255,0.9)';
    for(const cloud of clouds){const cx=cloud.x-cameraX*0.5;if(cx>-100&&cx<CANVAS_WIDTH+100)drawCloud(cx,cloud.y,cloud.size);}
    ctx.fillStyle='#2d8b2d';
    for(const bush of bushes){const bx=bush.x-cameraX*0.7;if(bx>-100&&bx<CANVAS_WIDTH+100)drawBush(bx,CANVAS_HEIGHT-45,bush.size);}
}
function drawCloud(x,y,s){ctx.beginPath();ctx.arc(x,y,s*0.5,0,Math.PI*2);ctx.arc(x+s*0.4,y-s*0.2,s*0.4,0,Math.PI*2);ctx.arc(x+s*0.8,y,s*0.45,0,Math.PI*2);ctx.arc(x+s*0.4,y+s*0.1,s*0.35,0,Math.PI*2);ctx.fill();}
function drawBush(x,y,s){ctx.beginPath();ctx.arc(x,y,s*0.4,0,Math.PI*2);ctx.arc(x+s*0.4,y-s*0.1,s*0.35,0,Math.PI*2);ctx.arc(x+s*0.8,y,s*0.4,0,Math.PI*2);ctx.fill();}
function drawFlagPole(){
    if(!flagPole)return;const x=flagPole.x-cameraX;
    ctx.fillStyle='#888';ctx.fillRect(x+5,flagPole.y,6,flagPole.height);
    ctx.fillStyle='#ffd700';ctx.beginPath();ctx.arc(x+8,flagPole.y,8,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#00cc00';ctx.beginPath();ctx.moveTo(x+11,flagPole.y+10);ctx.lineTo(x+50,flagPole.y+30);ctx.lineTo(x+11,flagPole.y+50);ctx.closePath();ctx.fill();
    ctx.fillStyle='#666';ctx.fillRect(x-10,flagPole.y+flagPole.height-10,36,10);
}

function updateUI(){document.getElementById('score').textContent=score;document.getElementById('coins').textContent=coins;document.getElementById('lives').textContent=lives;document.getElementById('timer').textContent=Math.max(0,Math.ceil(timer));}

function startGame(){
    document.getElementById('start-screen').style.display='none';
    gameState='playing';score=0;coins=0;lives=3;timer=300;cameraX=0;
    createLevel();updateUI();
    if(timerInterval)clearInterval(timerInterval);
    timerInterval=setInterval(()=>{if(gameState==='playing'){timer--;updateUI();if(timer<=0)mario.die();}},1000);
}
function gameOver(){
    gameState='gameover';if(timerInterval)clearInterval(timerInterval);
    document.getElementById('final-score').textContent=score;
    document.getElementById('game-over-screen').style.display='flex';
}
function winGame(){
    gameState='win';if(timerInterval)clearInterval(timerInterval);
    score+=Math.ceil(timer)*10;updateUI();
    document.getElementById('win-score').textContent=score;
    document.getElementById('win-screen').style.display='flex';
}
function restartGame(){
    document.getElementById('game-over-screen').style.display='none';
    document.getElementById('win-screen').style.display='none';
    startGame();
}

function gameLoop(){
    if(gameState==='playing'){
        mario.update(platforms,enemies,coinItems,pipes,flagPole);
        const aliveEnemies=[];
        for(const enemy of enemies){if(enemy.update(platforms))aliveEnemies.push(enemy);}
        const targetCamX=mario.x-CANVAS_WIDTH/3;
        cameraX+=(targetCamX-cameraX)*0.1;if(cameraX<0)cameraX=0;
        drawBackground();
        for(const plat of platforms){
            const px=plat.x-cameraX;
            if(px>-50&&px<CANVAS_WIDTH+50){
                if(plat.isQuestion){ctx.fillStyle='#ffd700';ctx.fillRect(px,plat.y,plat.width,plat.height);ctx.fillStyle='#b8860b';ctx.fillRect(px+2,plat.y+2,plat.width-4,plat.height-4);ctx.fillStyle='#ffd700';ctx.font='bold 24px Arial';ctx.textAlign='center';ctx.fillText('?',px+plat.width/2,plat.y+30);}
                else{ctx.fillStyle=plat.color;ctx.fillRect(px,plat.y,plat.width,plat.height);ctx.strokeStyle='#8b4513';ctx.lineWidth=1;ctx.strokeRect(px+1,plat.y+1,plat.width-2,plat.height-2);ctx.beginPath();ctx.moveTo(px+plat.width/2,plat.y);ctx.lineTo(px+plat.width/2,plat.y+plat.height);ctx.moveTo(px,plat.y+plat.height/2);ctx.lineTo(px+plat.width,plat.y+plat.height/2);ctx.stroke();}
            }
        }
        for(const pipe of pipes){const px=pipe.x-cameraX;if(px>-100&&px<CANVAS_WIDTH+100)pipe.draw(ctx,cameraX);}
        for(const coin of coinItems){const cx=coin.x-cameraX;if(cx>-50&&cx<CANVAS_WIDTH+50)coin.draw(ctx,cameraX);}
        for(const enemy of enemies){const ex=enemy.x-cameraX;if(ex>-50&&ex<CANVAS_WIDTH+50)enemy.draw(ctx,cameraX);}
        drawFlagPole();mario.draw(ctx,cameraX);
    }
    requestAnimationFrame(gameLoop);
}

document.addEventListener('keydown',(e)=>{
    keys[e.key]=true;
    if(e.key==='p'||e.key==='P'){if(gameState==='playing')gameState='paused';else if(gameState==='paused')gameState='playing';}
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(e.key))e.preventDefault();
});
document.addEventListener('keyup',(e)=>{keys[e.key]=false;});

createLevel();gameLoop();
