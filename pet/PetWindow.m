// 汤圆的桌面身体：透明、无边框、永远在顶层。
//
// 为什么不是 Python/cv2：cv2 的窗口不能透明，浏览器也不行。
// 只有原生 NSWindow 能让窗口背景真正透明，立绘才能"浮"在桌面上。

#import <Cocoa/Cocoa.h>
#import <sys/file.h>
#import <fcntl.h>
#import <unistd.h>

static NSString *const kMoodFile = @".tangyuan_mood";

// ------------------------------------------------------------------ 视图
@interface PetView : NSView
@property (nonatomic, strong) NSImage *baseImg;
@property (nonatomic, strong) NSImage *eyeImg;
@property (nonatomic, strong) NSImage *mouthImg;
@property (nonatomic) double sx, sy, dx, dy, rot;   // 呼吸/微晃/倾斜
@end

@implementation PetView
- (BOOL)isOpaque { return NO; }
- (void)drawRect:(NSRect)dirtyRect {
    [[NSColor clearColor] set];
    NSRectFillUsingOperation(dirtyRect, NSCompositingOperationCopy);

    // 以"脚底中点"为支点做变换：人站着晃，脚不能离地
    CGContextRef ctx = [[NSGraphicsContext currentContext] CGContext];
    CGContextSaveGState(ctx);
    NSPoint anchor = NSMakePoint(NSMidX(self.bounds), NSMinY(self.bounds));
    CGContextTranslateCTM(ctx, anchor.x + self.dx, anchor.y + self.dy);
    CGContextRotateCTM(ctx, self.rot * M_PI / 180.0);
    CGContextScaleCTM(ctx, self.sx, self.sy);
    CGContextTranslateCTM(ctx, -anchor.x, -anchor.y);

    [self.baseImg drawInRect:self.bounds];
    [self.eyeImg drawInRect:self.bounds];
    [self.mouthImg drawInRect:self.bounds];
    CGContextRestoreGState(ctx);
}
@end

// ------------------------------------------------------------- 可拖拽窗口
@interface DragWindow : NSWindow
@property (nonatomic) NSPoint grabOffset;
@end

@implementation DragWindow
- (BOOL)canBecomeKeyWindow { return YES; }
- (void)mouseDown:(NSEvent *)e {
    self.grabOffset = [NSEvent mouseLocation];
    NSPoint origin = self.frame.origin;
    self.grabOffset = NSMakePoint(self.grabOffset.x - origin.x,
                                  self.grabOffset.y - origin.y);
}
- (void)mouseDragged:(NSEvent *)e {
    NSPoint cur = [NSEvent mouseLocation];
    [self setFrameOrigin:NSMakePoint(cur.x - self.grabOffset.x,
                                     cur.y - self.grabOffset.y)];
}
@end

// ------------------------------------------------------------------ 主体
@interface PetApp : NSObject <NSApplicationDelegate>
@property (nonatomic, strong) DragWindow *window;
@property (nonatomic, strong) PetView *view;
@property (nonatomic, strong) NSStatusItem *statusItem;
@property (nonatomic, strong) NSMutableDictionary<NSString *, NSImage *> *bases;
@property (nonatomic, strong) NSMutableArray<NSImage *> *eyes;
@property (nonatomic, strong) NSMutableArray<NSImage *> *mouths;
@property (nonatomic, copy) NSString *mood;
@property (nonatomic) NSTimeInterval blinkStart;
@property (nonatomic) NSTimeInterval blinkLen;
@property (nonatomic) NSTimeInterval nextBlink;
@property (nonatomic) NSTimeInterval nextIdle;      // 下一个待机小动作
@property (nonatomic) NSTimeInterval idleStart;     // 当前小动作开始时间
@property (nonatomic) int idleKind;                 // 0 没有 / 1 歪头 / 2 挥手 / 3 伸懒腰
@property (nonatomic, copy) NSString *displayMood;  // 屏幕上实际用哪张图
@property (nonatomic) BOOL clickThrough;
@end

@implementation PetApp

- (NSURL *)assetDir {
    NSFileManager *fm = [NSFileManager defaultManager];
    NSString *home = [@"~/Downloads/robot-brain/assets/pet" stringByExpandingTildeInPath];
    if ([fm fileExistsAtPath:home]) return [NSURL fileURLWithPath:home];
    NSString *res = [[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:@"pet"];
    if ([fm fileExistsAtPath:res]) return [NSURL fileURLWithPath:res];
    return nil;
}

- (void)applicationDidFinishLaunching:(NSNotification *)note {
    [self loadAssets];
    [self makeWindow];
    [self makeMenu];
    self.nextBlink = [NSDate timeIntervalSinceReferenceDate] + 1.5;
    self.nextIdle = [NSDate timeIntervalSinceReferenceDate] + 8.0;
    self.displayMood = @"idle";
    self.view.sx = 1.0; self.view.sy = 1.0;
    [NSTimer scheduledTimerWithTimeInterval:1.0 / 30.0 target:self
                                   selector:@selector(tick:) userInfo:nil repeats:YES];
    [NSTimer scheduledTimerWithTimeInterval:0.25 target:self
                                   selector:@selector(pollMood:) userInfo:nil repeats:YES];
}

- (void)loadAssets {
    NSURL *dir = [self assetDir];
    if (!dir) {
        NSLog(@"找不到 assets/pet，先跑 python3 build_pet.py");
        [NSApp terminate:nil];
        return;
    }
    self.bases = [NSMutableDictionary dictionary];
    for (NSString *n in @[@"idle", @"blink", @"smile", @"surprised", @"talk",
                          @"sad", @"cry", @"angry", @"wave"]) {
        NSURL *u = [dir URLByAppendingPathComponent:
                    [NSString stringWithFormat:@"base_%@.png", n]];
        NSImage *img = [[NSImage alloc] initWithContentsOfURL:u];
        if (img) self.bases[n] = img;
    }
    self.eyes = [NSMutableArray array];
    for (int i = 0; i < 12; i++) {
        NSURL *u = [dir URLByAppendingPathComponent:
                    [NSString stringWithFormat:@"eyes_%02d.png", i]];
        NSImage *img = [[NSImage alloc] initWithContentsOfURL:u];
        if (img) [self.eyes addObject:img];
    }
    self.mouths = [NSMutableArray array];
    for (int i = 0; i < 8; i++) {
        NSURL *u = [dir URLByAppendingPathComponent:
                    [NSString stringWithFormat:@"mouth_%02d.png", i]];
        NSImage *img = [[NSImage alloc] initWithContentsOfURL:u];
        if (img) [self.mouths addObject:img];
    }
    NSLog(@"载入 %lu 个状态、%lu 个眼睛、%lu 个嘴",
          (unsigned long)self.bases.count,
          (unsigned long)self.eyes.count,
          (unsigned long)self.mouths.count);
    self.mood = @"idle";
}

- (void)makeWindow {
    NSSize size = NSMakeSize(230, 256);   // 裁过之后立绘是 623x693，按比例縮
    NSRect vis = NSScreen.mainScreen.visibleFrame;
    NSRect rect = NSMakeRect(NSMaxX(vis) - size.width - 40,
                             NSMinY(vis) + 40,
                             size.width, size.height);

    self.window = [[DragWindow alloc] initWithContentRect:rect
                                                styleMask:NSWindowStyleMaskBorderless
                                                  backing:NSBackingStoreBuffered
                                                    defer:NO];
    self.window.opaque = NO;
    self.window.backgroundColor = [NSColor clearColor];
    self.window.hasShadow = NO;
    self.window.level = NSFloatingWindowLevel;
    self.window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
                                     NSWindowCollectionBehaviorStationary |
                                     NSWindowCollectionBehaviorIgnoresCycle;

    self.view = [[PetView alloc] initWithFrame:NSMakeRect(0, 0, size.width, size.height)];
    self.window.contentView = self.view;
    [self.window makeKeyAndOrderFront:nil];
}

- (void)makeMenu {
    self.statusItem = [[NSStatusBar systemStatusBar]
                       statusItemWithLength:NSVariableStatusItemLength];
    self.statusItem.button.title = @"汤圆";

    NSMenu *menu = [[NSMenu alloc] init];
    [menu addItemWithTitle:@"点击穿透（鼠标穿过她）" action:@selector(toggleThrough) keyEquivalent:@"p"];
    [menu addItemWithTitle:@"回到右下角" action:@selector(resetPos) keyEquivalent:@"r"];
    [menu addItem:[NSMenuItem separatorItem]];
    [menu addItemWithTitle:@"退出" action:@selector(quitNow) keyEquivalent:@"q"];
    for (NSMenuItem *it in menu.itemArray) it.target = self;
    self.statusItem.menu = menu;
}

- (void)resetPos {
    NSRect vis = NSScreen.mainScreen.visibleFrame;
    [self.window setFrameOrigin:NSMakePoint(NSMaxX(vis) - self.window.frame.size.width - 40,
                                            NSMinY(vis) + 40)];
}

- (void)toggleThrough {
    self.clickThrough = !self.clickThrough;
    self.window.ignoresMouseEvents = self.clickThrough;
    NSMenuItem *it = self.statusItem.menu.itemArray.firstObject;
    it.state = self.clickThrough ? NSControlStateValueOn : NSControlStateValueOff;
    self.statusItem.button.title = self.clickThrough ? @"汤圆·穿透" : @"汤圆";
}

- (void)quitNow { [NSApp terminate:nil]; }

- (void)tick:(NSTimer *)timer {
    NSTimeInterval t = [NSDate timeIntervalSinceReferenceDate];

    // ---- 呼吸和微晃：都是对同一张图做变换，不是换图，所以不会闪
    double breath = sin(t * 0.85) * 0.0045;          // 起伏不到半个百分点
    self.view.sy = 1.0 + breath;
    self.view.sx = 1.0 - breath * 0.35;
    self.view.dx = sin(t * 0.21) * 1.6;
    self.view.dy = sin(t * 0.33 + 1.1) * 0.7;
    self.view.rot = sin(t * 0.17) * 0.3;

    // ---- 待机小动作：每隔十几秒来一下，让她不像个雕像
    if (self.idleKind == 0 && t >= self.nextIdle &&
        ([self.mood isEqualToString:@"idle"] || [self.mood isEqualToString:@"listening"])) {
        self.idleKind = 1 + arc4random_uniform(3);
        self.idleStart = t;
    }
    if (self.idleKind != 0) {
        double dur = (self.idleKind == 2) ? 2.4 : 1.8;
        double k = (t - self.idleStart) / dur;
        if (k >= 1.0) {
            self.idleKind = 0;
            self.nextIdle = t + 9.0 + (double)arc4random_uniform(14000) / 1000.0;
        } else {
            double env = sin(k * M_PI);              // 0→1→0，起落都柔和
            if (self.idleKind == 1) {                // 歪头
                self.view.rot += env * 1.6;
                self.view.dx += env * 2.0;
            } else if (self.idleKind == 3) {         // 伸个懒腰：轻轻拔高
                self.view.sy += env * 0.012;
                self.view.dy += env * 2.5;
            }
        }
    }

    // 屏幕上用哪张图：外面指定的情绪优先，其次可能是待机小动作里的"挥手"
    NSString *want = self.mood;
    if (self.idleKind == 2 && (t - self.idleStart) / 2.4 < 0.75) {
        want = @"wave";
    }
    self.displayMood = self.bases[want] ? want : @"idle";

    NSImage *eyeImg = nil;
    if (t >= self.nextBlink && self.blinkStart == 0) {
        self.blinkStart = t;
        self.blinkLen = 0.13 + (double)arc4random_uniform(60) / 1000.0;
    }
    if (self.blinkStart > 0) {
        double k = (t - self.blinkStart) / self.blinkLen;
        if (k >= 1.0) {
            self.blinkStart = 0;
            self.nextBlink = t + 1.6 + (double)arc4random_uniform(1800) / 1000.0;
        } else {
            double closed = k < 0.4 ? k / 0.4 : (1.0 - (k - 0.4) / 0.6);
            NSInteger idx = (NSInteger)(closed * 11.0);
            if (idx < 0) idx = 0;
            if (idx < (NSInteger)self.eyes.count) eyeImg = self.eyes[idx];
        }
    }

    NSImage *mouthImg = nil;
    if ([self.mood isEqualToString:@"talking"] && self.mouths.count > 0) {
        double v = (sin(t * 7.0) + 1.0) / 2.0;
        NSInteger idx = (NSInteger)(v * (self.mouths.count - 1));
        if (idx < 0) idx = 0;
        if (idx >= (NSInteger)self.mouths.count) idx = self.mouths.count - 1;
        mouthImg = self.mouths[idx];
    }

    self.view.baseImg = self.bases[self.displayMood] ?: self.bases[@"idle"];
    self.view.eyeImg = eyeImg;
    self.view.mouthImg = mouthImg;
    [self.view setNeedsDisplay:YES];
}

- (void)pollMood:(NSTimer *)timer {
    NSString *path = [kMoodFile stringByExpandingTildeInPath];
    NSString *s = [NSString stringWithContentsOfFile:path
                                            encoding:NSUTF8StringEncoding
                                               error:NULL];
    if (!s) return;
    s = [s stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    if (s.length && ![s isEqualToString:self.mood] && self.bases[s]) {
        self.mood = s;
        self.idleKind = 0;
        self.nextIdle = [NSDate timeIntervalSinceReferenceDate] + 12.0;
    }
}

@end

int main(int argc, const char *argv[]) {
    // 单例：已经有一个在跑就安静退出，不然桌面上会出现两个她
    int lockFd = open("/tmp/.tangyuan_pet.lock", O_CREAT | O_RDWR, 0644);
    if (lockFd >= 0 && flock(lockFd, LOCK_EX | LOCK_NB) != 0) {
        return 0;
    }
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        PetApp *delegate = [[PetApp alloc] init];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [app run];
    }
    return 0;
}
