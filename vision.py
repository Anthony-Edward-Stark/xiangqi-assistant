"""9x10 grid, piece circles and per-skin glyph templates learned from a full opening."""
from dataclasses import asdict, dataclass
from pathlib import Path
import cv2
import numpy as np
from rules import START_BOARD, color

TEMPLATE_FORMAT=3


@dataclass(frozen=True)
class Grid:
    x0: float
    y0: float
    x1: float
    y1: float
    width: int
    height: int
    source: str = "auto"

    @property
    def dx(self):
        return (self.x1-self.x0)/8

    @property
    def dy(self):
        return (self.y1-self.y0)/9

    def valid(self):
        return (0 <= self.x0 < self.x1 < self.width and 0 <= self.y0 < self.y1 < self.height
                and min(self.dx,self.dy) >= 18 and .85 < self.dx/self.dy < 1.15)

    def to_dict(self):
        return asdict(self)


def _clusters(values):
    groups=[]
    for value in sorted(values):
        if groups and value-np.mean(groups[-1]) < 3:
            groups[-1].append(value)
        else:
            groups.append([value])
    return np.array([np.mean(g) for g in groups])


def _fits(points, count, short):
    if len(points) < count-4:
        return []
    candidates=[]
    for a in points:
        for b in points:
            for separation in (1,2,3):
                step=(b-a)/separation
                if not short*.06 < step < short*.145:
                    continue
                for offset in range(3):
                    start=a-offset*step
                    targets=start+np.arange(count)*step
                    distances=np.abs(points[:,None]-targets[None,:])
                    close=distances.min(axis=0) < max(2,step*.10)
                    if close.sum() < count-3:
                        continue
                    ids=np.arange(count)[close]
                    actual=points[distances[:,close].argmin(axis=0)]
                    pitch,origin=np.polyfit(ids,actual,1)
                    error=float(np.sqrt(np.mean((actual-(origin+ids*pitch))**2)))
                    if error < 2:
                        candidates.append((float(close.sum())-error,origin,pitch))
    unique={}
    for score,start,step in candidates:
        key=(round(start/2),round(step/2))
        if key not in unique or unique[key][0] < score:
            unique[key]=(score,start,step)
    return sorted(unique.values(),reverse=True)[:24]


def grid_support(image, grid):
    if not grid.valid() or image.shape[:2] != (grid.height,grid.width):
        return 0
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    offset=max(4,round(min(grid.dx,grid.dy)*.13))
    hits=total=0
    for vertical in (False,True):
        for i in range(1,8 if vertical else 9):
            for j in range(9 if vertical else 8):
                if vertical and j == 4:
                    continue
                x=round(grid.x0+(i if vertical else j+.5)*grid.dx)
                y=round(grid.y0+(j+.5 if vertical else i)*grid.dy)
                if not (offset < x < grid.width-offset and offset < y < grid.height-offset):
                    continue
                if vertical:
                    line=float(gray[y-1:y+2,x-2:x+3].min(axis=1).mean())
                    bg=(int(gray[y,x-offset])+int(gray[y,x+offset]))/2
                else:
                    line=float(gray[y-2:y+3,x-1:x+2].min(axis=0).mean())
                    bg=(int(gray[y-offset,x])+int(gray[y+offset,x]))/2
                hits += bg-line > 10
                total += 1
    return hits/max(total,1)


def detect_grid(image):
    h,w=image.shape[:2]
    scale=min(1.,1000/max(h,w))
    small=cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    short=min(gray.shape)
    lines=cv2.HoughLinesP(cv2.Canny(gray,40,110),1,np.pi/180,threshold=30,
                          minLineLength=int(short*.22),maxLineGap=int(short*.075))
    if lines is None:
        return None
    xs,ys=[],[]
    for x,y,u,v in lines.reshape(-1,4):
        if abs(x-u) <= 2:
            xs.append((x+u)/2)
        if abs(y-v) <= 2:
            ys.append((y+v)/2)
    best=None
    for sx,x,dx in _fits(_clusters(xs),9,short):
        for sy,y,dy in _fits(_clusters(ys),10,short):
            if abs(dx/dy-1) > .12:
                continue
            g=Grid(x/scale,y/scale,(x+8*dx)/scale,(y+9*dy)/scale,w,h)
            if not g.valid():
                continue
            support=grid_support(image,g)
            score=sx+sy+support*12
            if support >= .35 and (best is None or score > best[0]):
                best=(score,g)
    return best[1] if best else None


def _circles(image, grid):
    step=min(grid.dx,grid.dy)
    scale=min(1.,72/step)
    padding=step*.48
    x0,y0=max(0,round(grid.x0-padding)),max(0,round(grid.y0-padding))
    x1,y1=min(grid.width,round(grid.x1+padding)),min(grid.height,round(grid.y1+padding))
    gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
    gray=cv2.resize(gray,None,fx=scale,fy=scale)
    gray=cv2.GaussianBlur(gray,(5,5),1)
    pitch=step*scale
    found=cv2.HoughCircles(gray,cv2.HOUGH_GRADIENT,1.2,minDist=pitch*.62,param1=100,param2=17,
                           minRadius=round(pitch*.28),maxRadius=round(pitch*.49))
    result={}
    if found is not None:
        for x,y,r in found[0]:
            x,y=float(x/scale+x0),float(y/scale+y0)
            col,row=round((x-grid.x0)/grid.dx),round((y-grid.y0)/grid.dy)
            if 0 <= col < 9 and 0 <= row < 10:
                error=np.hypot(x-(grid.x0+col*grid.dx),y-(grid.y0+row*grid.dy))
                if error < step*.20:
                    result[(col,row)]=(x,y,float(r/scale))
    # A visible circular rim can still establish occupancy when Hough misses it.
    full_gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    angles=np.linspace(0,2*np.pi,80,endpoint=False)
    angles=angles[(np.abs(np.sin(angles))>.18)&(np.abs(np.cos(angles))>.18)]
    radii=np.linspace(.32,.48,12)*step
    for row in range(10):
        for col in range(9):
            if (col,row) in result:
                continue
            x,y=grid.x0+col*grid.dx,grid.y0+row*grid.dy
            xx=np.rint(x+np.cos(angles)[:,None]*radii).astype(int)
            yy=np.rint(y+np.sin(angles)[:,None]*radii).astype(int)
            if xx.min()<0 or yy.min()<0 or xx.max()>=grid.width or yy.max()>=grid.height:
                continue
            samples=full_gray[yy,xx]
            threshold=min(165,float(np.percentile(samples,80))*.78)
            if np.mean(samples.min(axis=1)<threshold)>.68:
                result[(col,row)]=(float(x),float(y),step*.42)
    return result


def glyph(image, grid, col, row):
    step=min(grid.dx,grid.dy)
    # Shadows and move highlights shift Hough centres. Text crops use stable intersections.
    x,y=grid.x0+col*grid.dx,grid.y0+row*grid.dy
    r=round(step*.48)
    x,y=round(x),round(y)
    if not (r <= x < grid.width-r and r <= y < grid.height-r):
        return None,None
    patch=image[y-r:y+r+1,x-r:x+r+1]
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
    yy,xx=np.mgrid[-r:r+1,-r:r+1]
    disc=xx*xx+yy*yy < (r*.95)**2
    red=((hsv[:,:,0] < 13)|(hsv[:,:,0] > 165))&(hsv[:,:,1]>75)&(patch[:,:,2].astype(int)-patch[:,:,0]>35)&(patch[:,:,2].astype(float)>patch[:,:,1]*1.8)&disc
    threshold=min(85,float(np.percentile(gray[disc],80))*.68)
    # Saturated brown rims and shadows are excluded from the larger text crop.
    dark=(gray<threshold)&((hsv[:,:,1]<150)|(gray<45))&disc&~red
    side="red" if np.count_nonzero(red) > max(14,np.count_nonzero(dark)*.32) else "black"
    mask=red if side == "red" else dark
    # Full rings span nearly a cell; glyph strokes fit well inside the piece face.
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    cleaned=np.zeros_like(mask)
    for index in range(1,count):
        if stats[index,cv2.CC_STAT_WIDTH]<=step*.75 and stats[index,cv2.CC_STAT_HEIGHT]<=step*.75:
            cleaned|=labels==index
    mask=cleaned
    if np.count_nonzero(mask) < r*r*.025:
        return None,None
    ys,xs=np.where(mask)
    crop=mask[ys.min():ys.max()+1,xs.min():xs.max()+1].astype(np.uint8)*255
    # Keep aspect ratio and centre the glyph to tolerate tiny circle-detection shifts.
    factor=40/max(crop.shape)
    resized=cv2.resize(crop,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA)
    result=np.zeros((48,48),np.uint8)
    h,w=resized.shape
    result[(48-h)//2:(48-h)//2+h,(48-w)//2:(48-w)//2+w]=resized
    return side,result


class Recognizer:
    def __init__(self, path):
        self.path=Path(path)
        self.templates={}
        self.learned_grid=None
        try:
            with np.load(self.path,allow_pickle=False) as saved:
                if "_format_version" in saved.files and saved["_format_version"].item()==TEMPLATE_FORMAT:
                    self.templates={key:saved[key] for key in saved.files if key in "RNBAKCP rnbakcp".replace(" ","")}
                    if "_grid" in saved.files:
                        x0,y0,x1,y1,w,h=saved["_grid"].tolist()
                        learned=Grid(x0,y0,x1,y1,int(w),int(h))
                        if learned.valid():
                            self.learned_grid=learned
        except (OSError,ValueError):
            pass

    def learn(self, image, grid, orientation="auto"):
        circles=_circles(image,grid)
        expected={(x,y) for y,row in enumerate(START_BOARD) for x,p in enumerate(row) if p}
        if set(circles) != expected:
            return None
        samples={}
        colors={}
        for x,y in expected:
            side,mask=glyph(image,grid,x,y)
            if mask is None:
                return None
            colors[(x,y)]=side
            samples[(x,y)]=mask
        red_bottom=colors[(4,9)] == "red" and colors[(4,0)] == "black"
        black_bottom=colors[(4,9)] == "black" and colors[(4,0)] == "red"
        if not (red_bottom or black_bottom):
            return None
        if orientation != "auto" and (orientation == "red_bottom") != red_bottom:
            return None
        bank={}
        for x,y in expected:
            p=START_BOARD[y][x] if red_bottom else START_BOARD[9-y][8-x]
            if color(p) != colors[(x,y)]:
                return None
            bank.setdefault(p,[]).append(samples[(x,y)])
        self.templates={p:np.stack(masks) for p,masks in bank.items()}
        self.learned_grid=grid
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix(".tmp.npz")
        np.savez_compressed(temporary,_format_version=np.array(TEMPLATE_FORMAT),
                            _grid=np.array([grid.x0,grid.y0,grid.x1,grid.y1,grid.width,grid.height]),**self.templates)
        temporary.replace(self.path)
        return "red_bottom" if red_bottom else "black_bottom"

    @staticmethod
    def similarity(a,b):
        a=(a>100).astype(np.uint8)
        b=(b>100).astype(np.uint8)
        kernel=np.ones((3,3),np.uint8)
        dil_a=cv2.dilate(a,kernel)
        dil_b=cv2.dilate(b,kernel)
        return float(((a&dil_b).sum()+(b&dil_a).sum())/max(1,a.sum()+b.sum()))

    def read(self, image, grid, orientation="auto"):
        learned=self.learned_grid
        if (learned and grid.source!="manual" and (learned.width,learned.height)==(grid.width,grid.height)
                and max(abs(getattr(learned,k)-getattr(grid,k)) for k in ("x0","y0","x1","y1"))
                    < min(grid.dx,grid.dy)*.06):
            grid=learned
        support=grid_support(image,grid)
        if support < .32:
            raise ValueError("棋盘被遮挡或页面已改变")
        circles=_circles(image,grid)
        bank_ready=len(self.templates)==14
        learned=None
        if not bank_ready:
            learned=self.learn(image,grid,orientation)
            bank_ready=learned is not None
        display=[[""]*9 for _ in range(10)]
        display_sides=[[""]*9 for _ in range(10)]
        uncertain=[]
        scores=[]
        for x,y in circles:
            side,mask=glyph(image,grid,x,y)
            display_sides[y][x]=side or "?"
            matches=[]
            if mask is not None and bank_ready:
                for p,templates in self.templates.items():
                    if color(p)==side:
                        score=max(self.similarity(mask,sample) for sample in templates)
                        matches.append((score,p))
            matches.sort(reverse=True)
            if not matches or matches[0][0]<.76 or (len(matches)>1 and matches[0][0]-matches[1][0]<.055):
                display[y][x]="?"
                uncertain.append([x,y])
            else:
                display[y][x]=matches[0][1]
                scores.append(matches[0][0])
        if not circles:
            raise ValueError("未读到象棋棋子")
        direction=orientation
        if direction=="auto":
            king=next(((x,y) for y,row in enumerate(display) for x,p in enumerate(row) if p=="K"),None)
            other=next(((x,y) for y,row in enumerate(display) for x,p in enumerate(row) if p=="k"),None)
            if king and other:
                direction="red_bottom" if king[1]>other[1] else "black_bottom"
            else:
                direction=learned
        if direction not in ("red_bottom","black_bottom"):
            return {"board":None,"display":display,"display_sides":display_sides,"uncertain":uncertain,"orientation":None,"needs_templates":not bank_ready}
        board=display if direction=="red_bottom" else [row[::-1] for row in display[::-1]]
        return {"board":board,"display":display,"display_sides":display_sides,"uncertain":uncertain,"orientation":direction,
                "needs_templates":not bank_ready,"learned":bool(learned),
                "confidence":round(min(scores),3) if scores else None,"grid_support":round(support,3)}
