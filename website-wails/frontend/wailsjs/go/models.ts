export namespace main {
	
	export class AccountWithPlatform {
	    account: string;
	    platform: string;
	
	    static createFrom(source: any = {}) {
	        return new AccountWithPlatform(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.account = source["account"];
	        this.platform = source["platform"];
	    }
	}
	export class Stats {
	    total: number;
	    images: number;
	    videos: number;
	    tags: number;
	
	    static createFrom(source: any = {}) {
	        return new Stats(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.total = source["total"];
	        this.images = source["images"];
	        this.videos = source["videos"];
	        this.tags = source["tags"];
	    }
	}
	export class Media {
	    id: number;
	    platform: string;
	    account: string;
	    type: string;
	    filename: string;
	    folder: string;
	    full_path: string;
	    caption: string;
	    timestamp: string;
	    year: string;
	    tags: string[];
	    thumbnail: string;
	
	    static createFrom(source: any = {}) {
	        return new Media(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.platform = source["platform"];
	        this.account = source["account"];
	        this.type = source["type"];
	        this.filename = source["filename"];
	        this.folder = source["folder"];
	        this.full_path = source["full_path"];
	        this.caption = source["caption"];
	        this.timestamp = source["timestamp"];
	        this.year = source["year"];
	        this.tags = source["tags"];
	        this.thumbnail = source["thumbnail"];
	    }
	}
	export class FilterResult {
	    media: Media[];
	    stats: Stats;
	    total: number;
	
	    static createFrom(source: any = {}) {
	        return new FilterResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.media = this.convertValues(source["media"], Media);
	        this.stats = this.convertValues(source["stats"], Stats);
	        this.total = source["total"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class IdolAccount {
	    id: number;
	    group_id: number;
	    platform: string;
	    username: string;
	    enabled: boolean;
	    last_check_at: string;
	    last_download_at: string;
	
	    static createFrom(source: any = {}) {
	        return new IdolAccount(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.group_id = source["group_id"];
	        this.platform = source["platform"];
	        this.username = source["username"];
	        this.enabled = source["enabled"];
	        this.last_check_at = source["last_check_at"];
	        this.last_download_at = source["last_download_at"];
	    }
	}
	export class GroupNode {
	    id: number;
	    name: string;
	    icon: string;
	    color: string;
	    parent_id?: number;
	    sort_order: number;
	    children: GroupNode[];
	    accounts: IdolAccount[];
	
	    static createFrom(source: any = {}) {
	        return new GroupNode(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.icon = source["icon"];
	        this.color = source["color"];
	        this.parent_id = source["parent_id"];
	        this.sort_order = source["sort_order"];
	        this.children = this.convertValues(source["children"], GroupNode);
	        this.accounts = this.convertValues(source["accounts"], IdolAccount);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class GroupOption {
	    id: number;
	    name: string;
	    icon: string;
	    parent_id?: number;
	
	    static createFrom(source: any = {}) {
	        return new GroupOption(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.icon = source["icon"];
	        this.parent_id = source["parent_id"];
	    }
	}
	
	export class IdolRun {
	    id: number;
	    group_id: number;
	    status: string;
	    total_accounts: number;
	    checked_accounts: number;
	    new_posts_found: number;
	    new_posts_downloaded: number;
	    error: string;
	    started_at: string;
	    finished_at: string;
	
	    static createFrom(source: any = {}) {
	        return new IdolRun(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.group_id = source["group_id"];
	        this.status = source["status"];
	        this.total_accounts = source["total_accounts"];
	        this.checked_accounts = source["checked_accounts"];
	        this.new_posts_found = source["new_posts_found"];
	        this.new_posts_downloaded = source["new_posts_downloaded"];
	        this.error = source["error"];
	        this.started_at = source["started_at"];
	        this.finished_at = source["finished_at"];
	    }
	}
	export class ManualDownloadConfig {
	    platform: string;
	    usernames: string[];
	    quality: string;
	    delay: number;
	    use_archive: boolean;
	    max_workers: number;
	
	    static createFrom(source: any = {}) {
	        return new ManualDownloadConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.platform = source["platform"];
	        this.usernames = source["usernames"];
	        this.quality = source["quality"];
	        this.delay = source["delay"];
	        this.use_archive = source["use_archive"];
	        this.max_workers = source["max_workers"];
	    }
	}
	
	export class QueueItem {
	    id: number;
	    video_path: string;
	    thumbnail_path: string;
	    platform: string;
	    account: string;
	    title: string;
	    description: string;
	    tags: string;
	    privacy: string;
	    status: string;
	    youtube_url: string;
	    error: string;
	    attempts: number;
	    created_at: string;
	    started_at: string;
	    finished_at: string;
	
	    static createFrom(source: any = {}) {
	        return new QueueItem(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.video_path = source["video_path"];
	        this.thumbnail_path = source["thumbnail_path"];
	        this.platform = source["platform"];
	        this.account = source["account"];
	        this.title = source["title"];
	        this.description = source["description"];
	        this.tags = source["tags"];
	        this.privacy = source["privacy"];
	        this.status = source["status"];
	        this.youtube_url = source["youtube_url"];
	        this.error = source["error"];
	        this.attempts = source["attempts"];
	        this.created_at = source["created_at"];
	        this.started_at = source["started_at"];
	        this.finished_at = source["finished_at"];
	    }
	}
	export class QueueStats {
	    total: number;
	    pending: number;
	    uploading: number;
	    done: number;
	    failed: number;
	
	    static createFrom(source: any = {}) {
	        return new QueueStats(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.total = source["total"];
	        this.pending = source["pending"];
	        this.uploading = source["uploading"];
	        this.done = source["done"];
	        this.failed = source["failed"];
	    }
	}
	export class ReindexResult {
	    success: boolean;
	    message: string;
	    total: number;
	
	    static createFrom(source: any = {}) {
	        return new ReindexResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.message = source["message"];
	        this.total = source["total"];
	    }
	}
	
	export class TagWithCount {
	    name: string;
	    count: number;
	
	    static createFrom(source: any = {}) {
	        return new TagWithCount(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.count = source["count"];
	    }
	}

}

