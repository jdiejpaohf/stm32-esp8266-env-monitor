#include "dht.h"

#define DHT_READ   GPIO_ReadInputDataBit(GPIOC, GPIO_Pin_9)


void DHT_SetoutputMode(void)
{
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure; 
	
	// 2.打开外设时钟	GPIOC	PC9
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
	
	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_9;	// 配置引脚
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;	// 引脚模式   推挽输出

	// 4.初始化GPIO
	GPIO_Init(GPIOC, &GPIO_InitStructure);

	GPIO_SetBits(GPIOC, GPIO_Pin_9);	// 总线空闲（高电平）
}

void DHT_SetInputMode(void)
{
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure; 
	
	// 2.打开外设时钟	GPIOC	PC9
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);

	
	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_9;	// 配置引脚
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;	// 引脚模式   上拉输入

	// 4.初始化GPIO
	GPIO_Init(GPIOC, &GPIO_InitStructure);
}

// DHT开始信号
void DHT_Start(void)
{
	// 设置输出模式
	DHT_SetoutputMode();

	// 把总线拉低
	GPIO_ResetBits(GPIOC, GPIO_Pin_9);
	delay_ms(20);
	
	// 把总线拉高
	GPIO_SetBits(GPIOC, GPIO_Pin_9);
	delay_us(30);
	
}

// 返回1   表示失败     返回0   表示响应
uint32_t DHT_Check(void)
{
	uint32_t i = 0;
	// 设置输入模式
	DHT_SetInputMode();

	// 等待PC9出现低电平   设置超时处理
	while(DHT_READ == 1 && i < 100)
	{
		delay_us(1);
		i++;
	}
	if(i >= 100)
	{
		return 1;
	}
	i = 0;
	
	// 等待低电平持续80us   设置超时处理
	while(DHT_READ == 0 && i < 100)
	{
		delay_us(1);
		i++;
	}
	if(i >= 100)
		return 1;	// 返回1   表示没有响应 
	else
		return 0;	// 返回0   表示响应了
}

// 读取1bit数据   返回1   表示数字1     返回0   表示数字0
uint32_t DHT_ReadBit(void)
{
	uint32_t i = 0;
	
	// 等待低电平出现   设置超时处理
	while(DHT_READ == 1 && i < 100)
	{
		delay_us(1);
		i++;
	}
	i = 0;

	// 等待高电平出现   设置超时处理
	while(DHT_READ == 0 && i < 100)
	{
		delay_us(1);
		i++;
	}
	
	// 延时40us并判断电平状态
	delay_us(40);
	if(DHT_READ == 1)
		return 1;	// 数字1
	else
		return 0;	// 数字0
}

// 读取一个字节数据
uint8_t DHT_ReadByte(void)
{
	uint32_t i = 0;
	uint8_t data = 0;	// 0000 0000
	
	// 循环读取数据，并放入变量中   MSB   高位先出	// 第一次收到数字1   data=0000 0010
	for(i = 0; i < 8; i++)
	{
		// 思考：先左移还是先或？？？（这两句话的顺序有没有问题）
//		data = DHT_ReadBit();	// 0000 0001
//		data = data << 1;		// 0000 0010     是否需要进行位或？？？
		
		data <<= 1;
		data |= DHT_ReadBit();
	}
	
	return data;
}

//获取DHT的温湿度数据   返回1  说明失败     返回0  说明成功
uint32_t  DHT_GetData(uint8_t *buf)
{
	uint32_t i=0;
	
	//发送开始信号
	DHT_Start();
	
	//判断DHT是否响应
	if( DHT_Check() == 0 ) //说明响应
	{
		//循环获取5个字节数据
		for(i=0;i<5;i++)
		{
			buf[i] = DHT_ReadByte();
		}
		//对获取的数据进行校验
		if( buf[0]+buf[1]+buf[2]+buf[3] == buf[4] ) //说明校验正确
		{
			return 0; //说明获取数据成功
		}
		else
			return 1; //获取数据失败 因为校验失败
	}
	else
	{
		return 1; //获取数据失败 因为根本没响应
	}
}
